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

r"""Trains a model using either of PNet, RNet or ONet.

Usage:
```shell

$ python train_model.py \
	--network_name=PNet \ 
	--train_root_dir=/workspace/train/mtcnn \
	--dataset_root_dir=/workspace/datasets/mtcnn

$ python train_model.py \
	--network_name=RNet \ 
	--train_root_dir=/workspace/train/mtcnn \
	--dataset_root_dir=/workspace/datasets/mtcnn 

$ python train_model.py \
	--network_name=ONet \ 
	--train_root_dir=/workspace/train/mtcnn \
	--dataset_root_dir=/workspace/datasets/mtcnn  
```
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys
import os
import argparse

from trainers.SimpleNetworkTrainer import SimpleNetworkTrainer
from trainers.HardNetworkTrainer import HardNetworkTrainer

from nets.NetworkFactory import NetworkFactory

def parse_arguments(argv):
	parser = argparse.ArgumentParser()
	parser.add_argument('--network_name', type=str, help='The name of the network.', default='PNet')  
	parser.add_argument('--dataset_root_dir', type=str, help='The directory where the dataset files are stored.', default=None)
	parser.add_argument('--train_root_dir', type=str, help='Input train root directory where model weights are saved.', default=None)
	parser.add_argument('--base_learning_rate', type=float, help='Initial learning rate.', default=0.01)
	parser.add_argument('--max_number_of_epoch', type=int, help='The maximum number of training steps.', default=5)
	parser.add_argument('--log_every_n_steps', type=int, help='The frequency with which logs are print.', default=200)

	return(parser.parse_args(argv))

def main(args):
	if( not (args.network_name in ['PNet', 'RNet', 'ONet']) ):
		raise ValueError('The network name should be either PNet, RNet or ONet.')

	if(not args.dataset_root_dir):
		raise ValueError('You must supply input dataset directory with --dataset_root_dir.')

	if(args.train_root_dir):
		train_root_dir = args.train_root_dir
	else:
		train_root_dir = NetworkFactory.model_train_dir()

	if(args.network_name == 'PNet'):
		trainer = SimpleNetworkTrainer(args.network_name)
	else:
		trainer = HardNetworkTrainer(args.network_name)
		
	status = trainer.train(args.network_name, args.dataset_root_dir, train_root_dir, args.base_learning_rate, args.max_number_of_epoch, args.log_every_n_steps)
	if(status):
		print(args.network_name + ' - network is trained and weights are generated at ' + train_root_dir)
	else:
		print('Error training the model.')

if __name__ == '__main__':
	os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' 
	main(parse_arguments(sys.argv[1:]))


