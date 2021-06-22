# Copyright (C) 2020-2021 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""You may copy this file as the starting point of your own model."""

from openfl.federated import TensorFlowDataLoader, KerasDataLoader

import nibabel as nib
import os

import os
import tensorflow as tf
import numpy as np
import nibabel as nib

class DatasetGenerator:

    def __init__(self, crop_dim,
                 data_path,
                 batch_size=4,
                 train_test_split=0.80,
                 validate_test_split=0.5,
                 number_input_channels=1,
                 num_classes=1,
                 random_seed=816,
                 shard=0):

        self.data_path = os.path.abspath(os.path.expanduser(data_path))
        self.batch_size = batch_size
        self.crop_dim = [crop_dim, crop_dim, crop_dim, number_input_channels]
        self.train_test_split = train_test_split
        self.validate_test_split = validate_test_split
        self.num_input_channels = number_input_channels
        self.num_classes = num_classes
        self.random_seed = random_seed
        self.shard = shard  # For Horovod, gives different shard per worker

        self.create_file_list()

        self.ds_train, self.ds_val, self.ds_test = self.get_dataset()

    def create_file_list(self):
        """
        Get list of the files from the BraTS raw data
        Split into training and testing sets.
        """

        filenames = tf.io.gfile.glob(os.path.join(self.data_path, "*/*_seg.nii.gz"))
        
        """
        Create a dictionary of tuples with image filename and label filename
        """
        self.numFiles = len(filenames)
        self.filenames = {}
        for idx, filename in enumerate(filenames):
            self.filenames[idx] = [filename.replace("_seg.nii.gz", "_flair.nii.gz"), filename]


    def z_normalize_img(self, img):
        """
        Normalize the image so that the mean value for each image
        is 0 and the standard deviation is 1.
        """

        ## TODO: Correct this for multiple MRI channels
        return (img - np.mean(img)) / np.std(img)

    def crop(self, img, msk, randomize):
        """
        Randomly crop the image and mask
        """

        slices = []

        # Do we randomize?
        is_random = randomize and np.random.rand() > 0.5

        for idx in range(len(img.shape)-1):  # Go through each dimension

            cropLen = self.crop_dim[idx]
            imgLen = img.shape[idx]

            start = (imgLen-cropLen)//2

            ratio_crop = 0.20  # Crop up this this % of pixels for offset
            # Number of pixels to offset crop in this dimension
            offset = int(np.floor(start*ratio_crop))

            if offset > 0:
                if is_random:
                    start += np.random.choice(range(-offset, offset))
                    if ((start + cropLen) > imgLen):  # Don't fall off the image
                        start = (imgLen-cropLen)//2
            else:
                start = 0

            slices.append(slice(start, start+cropLen))

        return img[tuple(slices)], msk[tuple(slices)]

    def augment_data(self, img, msk):
        """
        Data augmentation
        Flip image and mask. Rotate image and mask.
        """

        # Determine if axes are equal and can be rotated
        # If the axes aren't equal then we can't rotate them.
        equal_dim_axis = []
        for idx in range(0, len(self.crop_dim)):
            for jdx in range(idx+1, len(self.crop_dim)):
                if self.crop_dim[idx] == self.crop_dim[jdx]:
                    equal_dim_axis.append([idx, jdx])  # Valid rotation axes
        dim_to_rotate = equal_dim_axis

        if np.random.rand() > 0.5:
            # Random 0,1 (axes to flip)
            ax = np.random.choice(np.arange(len(self.crop_dim)-1))
            img = np.flip(img, ax)
            msk = np.flip(msk, ax)

        elif (len(dim_to_rotate) > 0) and (np.random.rand() > 0.5):
            rot = np.random.choice([1, 2, 3])  # 90, 180, or 270 degrees

            # This will choose the axes to rotate
            # Axes must be equal in size
            random_axis = dim_to_rotate[np.random.choice(len(dim_to_rotate))]

            img = np.rot90(img, rot, axes=random_axis)  # Rotate axes 0 and 1
            msk = np.rot90(msk, rot, axes=random_axis)  # Rotate axes 0 and 1

        return img, msk

    def read_nifti_file(self, idx, randomize=False):
        """
        Read Nifti file
        """

        idx = idx.numpy()
        imgFile = self.filenames[idx][0]
        mskFile = self.filenames[idx][1]
        
        img_temp = np.array(nib.load(imgFile).dataobj)
        img_temp = np.rot90(img_temp)

        img = np.zeros(list(img_temp.shape) + [self.num_input_channels])
        # Normalize
        img_temp = self.z_normalize_img(img_temp)

        img[..., 0] = img_temp

        for channel in range(1, self.num_input_channels):

            if channel == 1:
                imgFile = self.filenames[idx][1].replace("_flair", "_t1")
            elif channel == 2:
                imgFile = self.filenames[idx][1].replace("_flair", "_t1ce")
            elif channel == 3:
                imgFile = self.filenames[idx][1].replace("_flair", "_t2")

            img_temp = np.array(nib.load(imgFile).dataobj)

            img_temp = np.rot90(img_temp)

            # Normalize
            img_temp = self.z_normalize_img(img_temp)

            img[...,channel] = img_temp


        #img = np.expand_dims(img, -1)

        msk = np.rot90(np.array(nib.load(mskFile).dataobj))
        msk = np.expand_dims(msk, -1)

        """
        "labels": {
             "0": "background",
             "1": "edema",
             "2": "non-enhancing tumor",
             "3": "enhancing tumour"}
         """
        # Combine all masks but background
        if self.number_output_classes == 1:
            msk[msk > 0] = 1.0
        else:
            msk_temp = np.zeros(list(msk.shape) + [self.number_output_classes])
            for channel in range(self.number_output_classes):
                msk_temp[msk == channel, channel] = 1.0
            msk = msk_temp

        # Crop
        img, msk = self.crop(img, msk, randomize)

        # Randomly rotate
        if randomize:
            img, msk = self.augment_data(img, msk)

        return img, msk

    def get_input_shape(self):

        return self.crop_dim

    def plot_images(self, ds, slice_num=90):
        """
        Plot images from dataset
        """
        import matplotlib.pyplot as plt

        plt.figure(figsize=(20, 20))

        num_cols = 2

        msk_channel = 0
        img_channel = 0

        for img, msk in ds.take(1):
            bs = img.shape[0]

            for idx in range(bs):
                plt.subplot(bs, num_cols, idx*num_cols + 1)
                plt.imshow(img[idx, :, :, slice_num, img_channel], cmap="bone")
                plt.title("MRI", fontsize=18)
                plt.subplot(bs, num_cols, idx*num_cols + 2)
                plt.imshow(msk[idx, :, :, slice_num, msk_channel], cmap="bone")
                plt.title("Tumor", fontsize=18)

        plt.show()

        print("Mean pixel value of image = {}".format(
            np.mean(img[0, :, :, :, 0])))

    def display_train_images(self, slice_num=90):
        """
        Plots some training images
        """
        self.plot_images(self.ds_train, slice_num)

    def display_validation_images(self, slice_num=90):
        """
        Plots some validation images
        """
        self.plot_images(self.ds_val, slice_num)

    def display_test_images(self, slice_num=90):
        """
        Plots some test images
        """
        self.plot_images(self.ds_test, slice_num)

    def get_train(self):
        """
        Return train dataset
        """
        return self.ds_train

    def get_test(self):
        """
        Return test dataset
        """
        return self.ds_test

    def get_validate(self):
        """
        Return validation dataset
        """
        return self.ds_val

    def get_dataset(self):
        """
        Create a TensorFlow data loader
        """
        self.num_train = int(self.numFiles * self.train_test_split)
        numValTest = self.numFiles - self.num_train

        ds = tf.data.Dataset.range(self.numFiles).shuffle(
            self.numFiles, self.random_seed)  # Shuffle the dataset

        """
        Horovod Sharding
        Here we are not actually dividing the dataset into shards
        but instead just reshuffling the training dataset for every
        shard. Then in the training loop we just go through the training
        dataset but the number of steps is divided by the number of shards.
        """
        ds_train = ds.take(self.num_train).shuffle(
            self.num_train, self.shard)  # Reshuffle based on shard
        ds_val_test = ds.skip(self.num_train)
        self.num_val = int(numValTest * self.validate_test_split)
        self.num_test = self.num_train - self.num_val
        ds_val = ds_val_test.take(self.num_val)
        ds_test = ds_val_test.skip(self.num_val)

        ds_train = ds_train.map(lambda x: tf.py_function(self.read_nifti_file,
                                                         [x, True], [tf.float32, tf.float32]),
                                num_parallel_calls=tf.data.experimental.AUTOTUNE)
        ds_val = ds_val.map(lambda x: tf.py_function(self.read_nifti_file,
                                                     [x, False], [tf.float32, tf.float32]),
                            num_parallel_calls=tf.data.experimental.AUTOTUNE)
        ds_test = ds_test.map(lambda x: tf.py_function(self.read_nifti_file,
                                                       [x, False], [tf.float32, tf.float32]),
                              num_parallel_calls=tf.data.experimental.AUTOTUNE)

        #ds_train = ds_train.repeat()
        ds_train = ds_train.batch(self.batch_size, drop_remainder=True)
        ds_train = ds_train.prefetch(tf.data.experimental.AUTOTUNE)

        batch_size_val = max(1, self.batch_size//2)    # Could be any batch size you'd like
        ds_val = ds_val.batch(batch_size_val, drop_remainder=True)
        ds_val = ds_val.prefetch(tf.data.experimental.AUTOTUNE)

        batch_size_test = max(1, self.batch_size//2)   # Could be any batch size you'd like
        ds_test = ds_test.batch(batch_size_test, drop_remainder=True)
        ds_test = ds_test.prefetch(tf.data.experimental.AUTOTUNE)

        return ds_train, ds_val, ds_test

class TensorFlowBratsDataLoader(TensorFlowDataLoader):
    """TensorFlow Data Loader for the BraTS dataset."""

    def __init__(self, data_path, batch_size=4, 
                 crop_dim=64, percent_train=0.8, 
                 pre_split_shuffle=True, 
                 number_input_channels=1,
                 num_classes=1,
                 **kwargs):
        """Initialize.

        Args:
            data_path: The file path for the BraTS dataset
            batch_size (int): The batch size to use
            crop_dim (int): Crop the original image to this size on each dimension
            percent_train (float): The percentage of the data to use for training (Default=0.8)
            pre_split_shuffle (bool): True= shuffle the dataset before
            performing the train/validate split (Default=True)
            **kwargs: Additional arguments, passed to super init 

        Returns:
            Data loader with BraTS data
        """
        super().__init__(batch_size, **kwargs)

        self.brats_data = DatasetGenerator(crop_dim,
                              data_path=data_path,
                              number_input_channels=number_input_channels,
                              batch_size=batch_size,
                              train_test_split=percent_train,
                              validate_test_split=0.5,
                              num_classes=num_classes,
                              random_seed=816)

        self.batch_size = batch_size
        self.crop_dim = crop_dim
        self.num_classes = num_classes


    def get_feature_shape(self):
        """Get the shape of an example feature array.
        Returns:
            tuple: shape of an example feature array
        """
        return self.brats_data.get_input_shape()

    def get_train_loader(self, batch_size=None, num_batches=None):
        """
        Get training data loader.
        Returns
        -------
        loader object
        """
        return self.brats_data.ds_train

    def get_valid_loader(self, batch_size=None):
        """
        Get validation data loader.
        Returns:
            loader object
        """
        return self.brats_data.ds_val

    def get_train_data_size(self):
        """
        Get total number of training samples.
        Returns:
            int: number of training samples
        """
        return self.brats_data.num_train

    def get_valid_data_size(self):
        """
        Get total number of validation samples.
        Returns:
            int: number of validation samples
        """
        return self.brats_data.num_val

