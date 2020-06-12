# -*- coding: utf-8 -*-
"""
Created on Tue Dec 10 19:46:17 2019

@author: Adnene Boumessouer
"""

import os
import shutil
import datetime
import json

import tensorflow as tf
from tensorflow import keras
import ktrain

import numpy as np
import pandas as pd

import models
from modules import metrics as custom_metrics
from modules import loss_functions as loss_functions

import matplotlib.pyplot as plt

# import seaborn as sns

# Learning Rate Finder Parameters
START_LR = 1e-5
LR_MAX_EPOCHS = 20


class AutoEncoder:
    def __init__(
        self,
        input_directory,
        architecture,
        color_mode,
        loss,
        batch_size=8,
        verbose=True,
    ):
        self.input_directory = input_directory
        self.color_mode = color_mode
        self.architecture = architecture
        self.loss = loss
        self.batch_size = batch_size

        self.verbose = verbose
        self.learner = None  # TO DO
        self.model_path = None  # TO DO
        self.hist = None  # TO DO

        # learning rate finder attributes
        self.opt_lr = None
        self.opt_lr_i = None
        self.base_lr = None
        self.base_lr_i = None

        self.epochs_trained = None

        self.save_dir = None
        self.log_dir = None

        # build model and preprocessing variables
        if architecture == "mvtec":
            self.model = models.mvtec.build_model(color_mode)
            self.rescale = models.mvtec.RESCALE
            self.shape = models.mvtec.SHAPE
            self.preprocessing_function = models.mvtec.PREPROCESSING_FUNCTION
            self.preprocessing = models.mvtec.PREPROCESSING
            self.vmin = models.mvtec.VMIN
            self.vmax = models.mvtec.VMAX
            self.dynamic_range = models.mvtec.DYNAMIC_RANGE
        elif architecture == "mvtec2":
            self.model = models.mvtec_2.build_model(color_mode)
            self.rescale = models.mvtec_2.RESCALE
            self.shape = models.mvtec_2.SHAPE
            self.preprocessing_function = models.mvtec_2.PREPROCESSING_FUNCTION
            self.preprocessing = models.mvtec_2.PREPROCESSING
            self.vmin = models.mvtec_2.VMIN
            self.vmax = models.mvtec_2.VMAX
            self.dynamic_range = models.mvtec_2.DYNAMIC_RANGE
        elif architecture == "resnet":
            self.model = models.resnet.build_model()
            self.rescale = models.resnet.RESCALE
            self.shape = models.resnet.SHAPE
            self.preprocessing_function = models.resnet.PREPROCESSING_FUNCTION
            self.preprocessing = models.resnet.PREPROCESSING
            self.vmin = models.resnet.VMIN
            self.vmax = models.resnet.VMAX
            self.dynamic_range = models.resnet.DYNAMIC_RANGE
        elif architecture == "nasnet":
            # self.model = models.nasnet.build_model()
            self.rescale = models.nasnet.RESCALE
            self.shape = models.nasnet.SHAPE
            self.preprocessing_function = models.nasnet.PREPROCESSING_FUNCTION
            self.preprocessing = models.nasnet.PREPROCESSING
            self.vmin = models.nasnet.VMIN
            self.vmax = models.nasnet.VMAX
            self.dynamic_range = models.nasnet.DYNAMIC_RANGE
            raise NotImplementedError("nasnet not yet implemented.")

        # set loss function
        if loss == "ssim":
            self.loss_function = loss_functions.ssim_loss(self.dynamic_range)
        elif loss == "mssim":
            self.loss_function = loss_functions.mssim_loss(self.dynamic_range)
        elif loss == "l2":
            self.loss_function = loss_functions.l2_loss
        elif loss == "mse":
            self.loss_function = keras.losses.mean_squared_error

        # set metrics to monitor training
        if color_mode == "grayscale":
            self.metrics = [custom_metrics.ssim_metric(self.dynamic_range)]
            self.hist_keys = ("loss", "val_loss", "ssim", "val_ssim")
        elif color_mode == "rgb":
            self.metrics = [custom_metrics.mssim_metric(self.dynamic_range)]
            self.hist_keys = ("loss", "val_loss", "mssim", "val_mssim")

        # compile model
        optimizer = keras.optimizers.Adam(learning_rate=START_LR)
        self.model.compile(loss=self.loss, optimizer=optimizer, metrics=self.metrics)

        return

    ### Methods for training =================================================

    def find_opt_lr(self, train_generator, validation_generator):
        # initialize learner object
        self.learner = ktrain.get_learner(
            model=self.model,
            train_data=train_generator,
            val_data=validation_generator,
            batch_size=self.batch_size,
        )

        if self.loss in ["ssim", "mssim"]:
            stop_factor = -6
        elif self.loss == ["l2", "mse"]:
            stop_factor = 6

        # simulate training while recording learning rate and loss
        self.learner.lr_find(
            start_lr=START_LR,
            lr_mult=1.01,
            max_epochs=LR_MAX_EPOCHS,
            stop_factor=stop_factor,
            show_plot=False,
        )
        losses = np.array(self.learner.lr_finder.losses)
        lrs = np.array(self.learner.lr_finder.lrs)

        # find optimal learning rate
        min_loss = np.amin(losses)
        min_loss_i = np.argmin(losses)
        # retrieve segment containing decreasing losses
        segment = losses[: min_loss_i + 1]
        max_loss = np.amax(segment)
        # compute optimal loss
        optimal_loss = max_loss - 0.85 * (max_loss - min_loss)
        # get index corresponding to optimal loss
        self.opt_lr_i = np.argwhere(segment < optimal_loss)[0][0]
        # get optimal learning rate
        self.opt_lr = float(lrs[self.opt_lr_i])
        # get base learning rate
        self.base_lr = self.opt_lr / 10
        self.base_lr_i = np.argwhere(lrs[:min_loss_i] > self.base_lr)[0][0]
        print("[INFO] learning rate finder complete.")
        print(f"\tbase learning rate: {self.base_lr:.2E}")
        print(f"\toptimal learning rate: {self.opt_lr:.2E}")
        # return opt_lr
        return

    def fit(self):
        # create tensorboard callback to monitor training
        tensorboard_cb = keras.callbacks.TensorBoard(
            log_dir=self.log_dir, write_graph=True, update_freq="epoch"
        )
        # Print command to paste in browser for visualizing in Tensorboard
        print("\ntensorboard --logdir={}\n".format(self.log_dir))

        # fit model using Cyclical Learning Rates
        self.hist = self.learner.autofit(
            self.opt_lr,
            epochs=None,
            early_stopping=20,
            reduce_on_plateau=5,
            reduce_factor=2,
            cycle_momentum=True,
            max_momentum=0.95,
            min_momentum=0.85,
            monitor="val_loss",  # Check this
            checkpoint_folder=None,
            verbose=1,
            callbacks=[tensorboard_cb],
        )

    ### Methods to create directory structure ===========================

    def create_save_dir(self):
        # create a directory to save model
        now = datetime.datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
        save_dir = os.path.join(
            os.getcwd(),
            "saved_models",
            self.input_directory,
            self.architecture,
            self.loss,
            now,
        )
        if not os.path.isdir(save_dir):
            os.makedirs(save_dir)
        self.save_dir = save_dir
        # create a log directory for tensorboard
        log_dir = os.path.join(save_dir, "logs")
        if not os.path.isdir(log_dir):
            os.makedirs(log_dir)
        self.log_dir = log_dir
        return

    def create_model_name(self):
        self.model_name = "CAE_" + self.architecture + "_b{}".format(self.batch_size)
        # model_path = os.path.join(save_dir, model_name + ".h5")
        self.model_path = os.path.join(self.save_dir, self.model_name + ".hdf5")
        return

    ### Methods for getting information about the training process ========

    def get_history_dict(self):
        hist_dict = dict((key, self.hist.history[key]) for key in self.hist_keys)
        return hist_dict

    def get_best_epoch(self):
        """
        Returns the epoch where the model had stopped training.
        This epoch corresponds with the smallest val_loss registered during training.
        """
        hist_dict = self.get_history_dict()
        best_epoch = np.argmin(np.array(hist_dict["val_loss"]))
        return best_epoch

    def get_best_val_loss(self):
        """
        Returns the smallest val_loss registered during training.
        This value also corresponds with the epoch where the model stopped training.
        """
        hist_dict = self.get_history_dict()
        epochs_trained = np.argmin(np.array(hist_dict["val_loss"]))
        best_val_loss = np.array(hist_dict["val_loss"])[epochs_trained]
        return best_val_loss

    ### Methods for plotting ============================================

    def lr_plot(self, close=False):
        losses = np.array(self.learner.lr_finder.losses)
        lrs = np.array(self.learner.lr_finder.lrs)
        i = self.opt_lr_i
        j = self.base_lr_i
        with plt.style.context("seaborn-darkgrid"):
            fig, ax = plt.subplots()
            plt.ylabel("loss")
            plt.xlabel("learning rate (log scale)")
            ax.plot(lrs[10:-1], losses[10:-1])
            plt.xscale("log")
            ax.plot(
                lrs[j],
                losses[j],
                markersize=10,
                marker="o",
                color="green",
                label="base_lr",
            )
            ax.plot(
                lrs[i],
                losses[i],
                markersize=10,
                marker="o",
                color="red",
                abel="opt_lr",
            )
            plt.title(
                f"Learning Rate Plot \nbase learning rate: {lrs[j]:.2E}\noptimal learning rate: {lrs[i]:.2E}"
            )
            ax.legend()
            plt.show()
        if close:
            plt.close()
            return fig
        print(f"[info] optimal learning rate: {lrs[i]:.2E}")

    def lr_schedule_plot(self, close=False):
        with plt.style.context("seaborn-darkgrid"):
            fig, _ = plt.subplots()
            self.learner.plot(plot_type="lr")
            plt.title("Cyclical Learning Rate Scheduler")
            plt.show()
        if close:
            plt.close()
            return fig

    def loss_plot(self, close=False):
        hist_dict = self.get_history_dict()
        hist_df = pd.DataFrame(hist_dict)
        with plt.style.context("seaborn-darkgrid"):
            fig = hist_df.plot().get_figure()
            plt.title("Loss Plot")
            plt.show()
        if close:
            plt.close()
            return fig

    ### Methods to save model and data ====================

    ### Methods to load model (and data?) =================
