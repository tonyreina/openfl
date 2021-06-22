import tensorflow as tf

def dice_coef(target, prediction, axis=(1, 2, 3), smooth=0.0001):
        """
        Sorenson Dice
        \frac{  2 \times \left | T \right | \cap \left | P \right |}{ \left | T \right | +  \left | P \right |  }
        where T is ground truth mask and P is the prediction mask
        """
        prediction = tf.round(prediction)  # Round to 0 or 1

        intersection = tf.reduce_sum(target * prediction, axis=axis)
        union = tf.reduce_sum(target + prediction, axis=axis)
        numerator = tf.constant(2.) * intersection + smooth
        denominator = union + smooth
        coef = numerator / denominator

        return tf.reduce_mean(coef)


def soft_dice_coef(target, prediction, axis=(1, 2, 3), smooth=0.0001):
    """
    Sorenson (Soft) Dice - Don't round predictions
    \frac{  2 \times \left | T \right | \cap \left | P \right |}{ \left | T \right | +  \left | P \right |  }
    where T is ground truth mask and P is the prediction mask
    """
    intersection = tf.reduce_sum(target * prediction, axis=axis)
    union = tf.reduce_sum(target + prediction, axis=axis)
    numerator = tf.constant(2.) * intersection + smooth
    denominator = union + smooth
    coef = numerator / denominator

    return tf.reduce_mean(coef)


def dice_loss(target, prediction, axis=(1, 2, 3), smooth=0.0001):
    """
    Sorenson (Soft) Dice loss
    Using -log(Dice) as the loss since it is better behaved.
    Also, the log allows avoidance of the division which
    can help prevent underflow when the numbers are very small.
    """
    intersection = tf.reduce_sum(prediction * target, axis=axis)
    p = tf.reduce_sum(prediction, axis=axis)
    t = tf.reduce_sum(target, axis=axis)
    numerator = tf.reduce_mean(intersection + smooth)
    denominator = tf.reduce_mean(t + p + smooth)
    dice_loss = -tf.math.log(2.*numerator) + tf.math.log(denominator)

    return dice_loss


def build_model(input_shape,
                n_cl_out=1,
                use_upsampling=False,
                dropout=0.2,
                print_summary=True,
                seed=816,
                depth=5,
                dropout_at=[2, 3],
                initial_filters=16,
                batch_norm=True,
                **kwargs):
    """Build the TensorFlow model.

    Args:
        input_tensor: input shape ot the model
        use_upsampling (bool): True = use bilinear interpolation;
                            False = use transposed convolution (Default=False)
        n_cl_out (int): Number of channels in output layer (Default=1)
        dropout (float): Dropout percentage (Default=0.2)
        print_summary (bool): True = print the model summary (Default = True)
        seed: random seed (Default=816)
        depth (int): Number of max pooling layers in encoder (Default=5)
        dropout_at: Layers to perform dropout after (Default=[2,3])
        initial_filters (int): Number of filters in first convolutional
        layer (Default=16)
        batch_norm (bool): True = use batch normalization (Default=True)
        **kwargs: Additional parameters to pass to the function

    """
    
    if (input_shape[0] % ((depth-1)**2)) > 0:
        raise ValueError(f'Crop dimension must be a multiple of 2^(depth of U-Net - 1) = {(depth - 1)**2}')

    inputs = tf.keras.layers.Input(input_shape, name="brats_mr_image")

    activation = tf.keras.activations.relu
    
    params = dict(kernel_size=(3, 3, 3), activation=activation,
                padding='same', 
                kernel_initializer=tf.keras.initializers.he_uniform(seed=seed))

    convb_layers = {}

    net = inputs
    filters = initial_filters
    for i in range(depth):
        name = 'conv{}a'.format(i + 1)
        net = tf.keras.layers.Conv3D(name=name, filters=filters, **params)(net)
        if i in dropout_at:
            net = tf.keras.layers.Dropout(dropout)(net)
        name = 'conv{}b'.format(i + 1)
        net = tf.keras.layers.Conv3D(name=name, filters=filters, **params)(net)
        if batch_norm:
            net = tf.keras.layers.BatchNormalization()(net)
        convb_layers[name] = net
        # only pool if not last level
        if i != depth - 1:
            name = 'pool{}'.format(i + 1)
            net = tf.keras.layers.MaxPooling3D(name=name, pool_size=(2, 2, 2))(net)
            filters *= 2

    # do the up levels
    filters //= 2
    for i in range(depth - 1):
        if use_upsampling:
            up = tf.keras.layers.UpSampling3D(
                name='up{}'.format(depth + i + 1), size=(2, 2, 2))(net)
        else:
            up = tf.keras.layers.Conv3DTranspose(
                name='transConv{}'.format(depth + i + 1), filters=filters, 
                kernel_size=(2, 2, 2), strides=(2, 2, 2), padding='same')(net)
        net = tf.keras.layers.concatenate(
            [up, convb_layers['conv{}b'.format(depth - i - 1)]],
            axis=-1
        )
        net = tf.keras.layers.Conv3D(
            name='conv{}a'.format(depth + i + 1),
            filters=filters, **params)(net)
        net = tf.keras.layers.Conv3D(
            name='conv{}b'.format(depth + i + 1),
            filters=filters, **params)(net)
        filters //= 2

    net = tf.keras.layers.Conv3D(name='prediction', filters=n_cl_out,
                                kernel_size=(1, 1, 1), 
                                activation='sigmoid')(net)

    model = tf.keras.models.Model(inputs=[inputs], outputs=[net])

    return model