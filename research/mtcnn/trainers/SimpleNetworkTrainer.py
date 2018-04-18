# Copyright 2018 The TensorFlow Authors All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import numpy as np
import random
import cv2
import tensorflow as tf
from tensorflow.contrib import slim

from trainers.AbstractNetworkTrainer import AbstractNetworkTrainer
from datasets.TensorFlowDataset import TensorFlowDataset

from losses.class_loss_ohem import class_loss_ohem
from losses.bounding_box_loss_ohem import bounding_box_loss_ohem
from losses.landmark_loss_ohem import landmark_loss_ohem

class SimpleNetworkTrainer(AbstractNetworkTrainer):

	def __init__(self, network_name='PNet'):	
		AbstractNetworkTrainer.__init__(self, network_name)	

	def _train_model(self, base_lr, loss, data_num):

    		lr_factor = 0.1
    		global_step = tf.Variable(0, trainable=False)
    		#LR_EPOCH [8,14]
    		#boundaried [num_batch,num_batch]
    		boundaries = [int(epoch * data_num / self._config.BATCH_SIZE) for epoch in self._config.LR_EPOCH]
    		#lr_values[0.01,0.001,0.0001,0.00001]
    		lr_values = [base_lr * (lr_factor ** x) for x in range(0, len(self._config.LR_EPOCH) + 1)]
    		#control learning rate
    		lr_op = tf.train.piecewise_constant(global_step, boundaries, lr_values)
    		optimizer = tf.train.MomentumOptimizer(lr_op, 0.9)
    		train_op = optimizer.minimize(loss, global_step)

    		return( train_op, lr_op )

	def _random_flip_images(self, image_batch, label_batch, landmark_batch):
    		if random.choice([0,1]) > 0:
        		num_images = image_batch.shape[0]
        		fliplandmarkindexes = np.where(label_batch==-2)[0]
        		flipposindexes = np.where(label_batch==1)[0]
        		#only flip
        		flipindexes = np.concatenate((fliplandmarkindexes,flipposindexes))
        		#random flip    
        		for i in flipindexes:
            			cv2.flip(image_batch[i],1,image_batch[i])        
        
        		#pay attention: flip landmark    
        		for i in fliplandmarkindexes:
            			landmark_ = landmark_batch[i].reshape((-1,2))
            			landmark_ = np.asarray([(1-x, y) for (x, y) in landmark_])
            			landmark_[[0, 1]] = landmark_[[1, 0]]#left eye<->right eye
            			landmark_[[3, 4]] = landmark_[[4, 3]]#left mouth<->right mouth        
            			landmark_batch[i] = landmark_.ravel()
        
    		return( image_batch, landmark_batch )

	def _calculate_accuracy(self, cls_prob,label):
    		pred = tf.argmax(cls_prob,axis=1)
	    	label_int = tf.cast(label,tf.int64)
    		cond = tf.where(tf.greater_equal(label_int,0))
    		picked = tf.squeeze(cond)
    		label_picked = tf.gather(label_int,picked)
    		pred_picked = tf.gather(pred,picked)
    		accuracy_op = tf.reduce_mean(tf.cast(tf.equal(label_picked,pred_picked),tf.float32))
    		return accuracy_op

	def train(self, network_name, dataset_dir, model_train_dir):
		model_train_dir = self.model_train_dir(model_train_dir)
		if(not os.path.exists(model_train_dir)):
			os.makedirs(model_train_dir)

		base_lr = 0.01
		end_epoch = 30

		label_file = os.path.join(dataset_dir, self.network_name(), 'image_list.txt')
	    	print( label_file )
    		f = open(label_file, 'r')
    		num = len(f.readlines())

		dataset_dir = self.dataset_dir(dataset_dir)		
		tensorflow_file_name = os.path.join(dataset_dir, 'image_list.tfrecord')

		image_size = self.network_size()
		tensorflow_dataset = TensorFlowDataset()
		image_batch, label_batch, bbox_batch, landmark_batch = tensorflow_dataset.read_single_tfrecord(tensorflow_file_name, self._config.BATCH_SIZE, image_size)

		radio_cls_loss = 1.0
		radio_bbox_loss = 0.5
		radio_landmark_loss = 0.5

    		input_image = tf.placeholder(tf.float32, shape=[self._config.BATCH_SIZE, image_size, image_size, 3], name='input_image')
    		label = tf.placeholder(tf.float32, shape=[self._config.BATCH_SIZE], name='label')
    		bounding_box_targets = tf.placeholder(tf.float32, shape=[self._config.BATCH_SIZE, 4], name='bbox_target')
    		landmark_targets = tf.placeholder(tf.float32,shape=[self._config.BATCH_SIZE,10],name='landmark_target')

		output_class_probability, output_bounding_box, output_landmarks = self._network.setup_network(input_image)
		class_loss = class_loss_ohem(output_class_probability, label)
           	bounding_box_loss = bounding_box_loss_ohem(output_bounding_box, bounding_box_targets, label)
            	landmark_loss = landmark_loss_ohem(output_landmarks, landmark_targets, label)

		class_accuracy = self._calculate_accuracy(output_class_probability, label)
		#L2_loss = tf.add_n(slim.losses.get_regularization_losses())
		L2_loss = tf.add_n(tf.losses.get_regularization_losses())

		train_op, lr_op = self._train_model(base_lr, radio_cls_loss*class_loss + radio_bbox_loss*bounding_box_loss + radio_landmark_loss*landmark_loss + L2_loss, num)

    		init = tf.global_variables_initializer()
    		sess = tf.Session()

    		saver = tf.train.Saver(max_to_keep=5)
    		sess.run(init)

    		tf.summary.scalar("class_loss", class_loss)
    		tf.summary.scalar("bounding_box_loss",bounding_box_loss)
    		tf.summary.scalar("landmark_loss",landmark_loss)
    		tf.summary.scalar("class_accuracy",class_accuracy)
    		summary_op = tf.summary.merge_all()

    		logs_dir = tensorflow_file_name = os.path.join(model_train_dir, "logs")

		if(not os.path.exists(logs_dir)):
			os.makedirs(logs_dir)

    		writer = tf.summary.FileWriter(logs_dir, sess.graph)

    		coord = tf.train.Coordinator()

    		threads = tf.train.start_queue_runners(sess=sess, coord=coord)
    		i = 0

    		MAX_STEP = int(num / self._config.BATCH_SIZE + 1) * end_epoch
    		epoch = 0
    		sess.graph.finalize()    

		return(True)

