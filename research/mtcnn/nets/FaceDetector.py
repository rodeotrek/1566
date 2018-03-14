from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import time
import cv2
import numpy as np

from nets.nms import py_nms

from nets.PNet import PNet
from nets.RNet import RNet
from nets.ONet import ONet

class FaceDetector(object):

	def __init__(self):
		print('FaceDetector')
		self.min_face_size = 24
		self.threshold = [0.9, 0.6, 0.7]
		self.scale_factor = 0.79

		self.pnet = PNet()
		self.pnet.load_model('/git-space/mtcnn/research/mtcnn/data/mtcnn/PNet/PNet')

		self.rnet = RNet()
		self.rnet.load_model('/git-space/mtcnn/research/mtcnn/data/mtcnn/RNet/RNet')

		self.onet = ONet()
		print('FaceDetector-done')

    	def generate_bbox(self, cls_map, reg, scale, threshold):
 
        	stride = 2
        	#stride = 4
        	cellsize = 12
        	#cellsize = 25

        	t_index = np.where(cls_map > threshold)

        	# find nothing
        	if t_index[0].size == 0:
            		return( np.array([]) )
        	#offset
        	dx1, dy1, dx2, dy2 = [reg[t_index[0], t_index[1], i] for i in range(4)]

        	reg = np.array([dx1, dy1, dx2, dy2])
        	score = cls_map[t_index[0], t_index[1]]
        	boundingbox = np.vstack([np.round((stride * t_index[1]) / scale),
                                 np.round((stride * t_index[0]) / scale),
                                 np.round((stride * t_index[1] + cellsize) / scale),
                                 np.round((stride * t_index[0] + cellsize) / scale),
                                 score,
                                 reg])

        	return( boundingbox.T )

	def processed_image(self, image, scale):
	        height, width, channels = image.shape
	        new_height = int(height * scale)
	        new_width = int(width * scale)
	        new_shape = (new_width, new_height)
	        resized_image = cv2.resize(image, new_shape, interpolation = cv2.INTER_LINEAR)
	        resized_image = (resized_image - 127.5) / 128
	        return( resized_image )

    	def convert_to_square(self, bbox): 
        	square_bbox = bbox.copy()
        	h = bbox[:, 3] - bbox[:, 1] + 1
        	w = bbox[:, 2] - bbox[:, 0] + 1
        	max_side = np.maximum(h, w)
        	square_bbox[:, 0] = bbox[:, 0] + w * 0.5 - max_side * 0.5
        	square_bbox[:, 1] = bbox[:, 1] + h * 0.5 - max_side * 0.5
        	square_bbox[:, 2] = square_bbox[:, 0] + max_side - 1
        	square_bbox[:, 3] = square_bbox[:, 1] + max_side - 1
        	return( square_bbox )

    	def pad(self, bboxes, w, h):
 
        	tmpw, tmph = bboxes[:, 2] - bboxes[:, 0] + 1, bboxes[:, 3] - bboxes[:, 1] + 1
        	num_box = bboxes.shape[0]

        	dx, dy = np.zeros((num_box,)), np.zeros((num_box,))
        	edx, edy = tmpw.copy() - 1, tmph.copy() - 1

        	x, y, ex, ey = bboxes[:, 0], bboxes[:, 1], bboxes[:, 2], bboxes[:, 3]

        	tmp_index = np.where(ex > w - 1)
        	edx[tmp_index] = tmpw[tmp_index] + w - 2 - ex[tmp_index]
        	ex[tmp_index] = w - 1

        	tmp_index = np.where(ey > h - 1)
        	edy[tmp_index] = tmph[tmp_index] + h - 2 - ey[tmp_index]
        	ey[tmp_index] = h - 1

        	tmp_index = np.where(x < 0)
        	dx[tmp_index] = 0 - x[tmp_index]
        	x[tmp_index] = 0

        	tmp_index = np.where(y < 0)
        	dy[tmp_index] = 0 - y[tmp_index]
        	y[tmp_index] = 0

        	return_list = [dy, edy, dx, edx, y, ey, x, ex, tmpw, tmph]
        	return_list = [item.astype(np.int32) for item in return_list]

        	return( return_list )

	def propose_faces(self, image):
        	h, w, c = image.shape
        	net_size = self.pnet.network_size
        
        	current_scale = float(net_size) / self.min_face_size
        	resized_image = self.processed_image(image, current_scale)
        	current_height, current_width, _ = resized_image.shape
        	
        	all_boxes = list()
        	while min(current_height, current_width) > net_size:
            		cls_cls_map, reg = self.pnet.detect(resized_image)
            		boxes = self.generate_bbox(cls_cls_map[:, :,1], reg, current_scale, self.threshold[0])

            		current_scale *= self.scale_factor
            		resized_image = self.processed_image(image, current_scale)
            		current_height, current_width, _ = resized_image.shape

            		if boxes.size == 0:
                		continue
            		keep = py_nms(boxes[:, :5], 0.5, 'Union')
            		boxes = boxes[keep]
            		all_boxes.append(boxes)

        	if len(all_boxes) == 0:
            		return None, None, None

        	all_boxes = np.vstack(all_boxes)

        	# merge the detection from first stage
        	keep = py_nms(all_boxes[:, 0:5], 0.7, 'Union')
        	all_boxes = all_boxes[keep]
        	boxes = all_boxes[:, :5]

        	bbw = all_boxes[:, 2] - all_boxes[:, 0] + 1
        	bbh = all_boxes[:, 3] - all_boxes[:, 1] + 1

        	# refine the boxes
        	boxes_c = np.vstack([all_boxes[:, 0] + all_boxes[:, 5] * bbw,
                             all_boxes[:, 1] + all_boxes[:, 6] * bbh,
                             all_boxes[:, 2] + all_boxes[:, 7] * bbw,
                             all_boxes[:, 3] + all_boxes[:, 8] * bbh,
                             all_boxes[:, 4]])
        	boxes_c = boxes_c.T

        	return( boxes, boxes_c, None )

    	def calibrate_box(self, bbox, reg):
        	bbox_c = bbox.copy()
        	w = bbox[:, 2] - bbox[:, 0] + 1
        	w = np.expand_dims(w, 1)
        	h = bbox[:, 3] - bbox[:, 1] + 1
        	h = np.expand_dims(h, 1)
        	reg_m = np.hstack([w, h, w, h])
        	aug = reg_m * reg
        	bbox_c[:, 0:4] = bbox_c[:, 0:4] + aug
        	return bbox_c

	def refine_faces(self, im, dets):
        	h, w, c = im.shape
        	dets = self.convert_to_square(dets)
        	dets[:, 0:4] = np.round(dets[:, 0:4])

        	[dy, edy, dx, edx, y, ey, x, ex, tmpw, tmph] = self.pad(dets, w, h)
        	num_boxes = dets.shape[0]
        	cropped_ims = np.zeros((num_boxes, 24, 24, 3), dtype=np.float32)
        	for i in range(num_boxes):
            		tmp = np.zeros((tmph[i], tmpw[i], 3), dtype=np.uint8)
            		tmp[dy[i]:edy[i] + 1, dx[i]:edx[i] + 1, :] = im[y[i]:ey[i] + 1, x[i]:ex[i] + 1, :]
            		cropped_ims[i, :, :, :] = (cv2.resize(tmp, (24, 24))-127.5) / 128
	        cls_scores, reg, _ = self.rnet.detect(cropped_ims)
        	cls_scores = cls_scores[:,1]
        	keep_inds = np.where(cls_scores > self.threshold[1])[0]
        	if len(keep_inds) > 0:
            		boxes = dets[keep_inds]
            		boxes[:, 4] = cls_scores[keep_inds]
            		reg = reg[keep_inds]
            		#landmark = landmark[keep_inds]
        	else:
            		return( None, None, None )        
        
        	keep = py_nms(boxes, 0.6)
        	boxes = boxes[keep]
        	boxes_c = self.calibrate_box(boxes, reg[keep])
        	return( boxes, boxes_c, None )

	def outpute_faces(self, image, boxes_c):
		return(self.onet.detect(image, boxes_c))

	def detect(self, image):
		boxes = None

		start_time = time.time()
		pnet_time = 0
        	if self.pnet:
            		boxes, boxes_c, _ = self.propose_faces(image)
            		if boxes_c is None:
                		return( np.array([]), np.array([]) )    
            		pnet_time = time.time() - start_time
            	
		start_time = time.time()
		rnet_time = 0
        	if self.rnet:
            		boxes, boxes_c, _ = self.refine_faces(image, boxes_c)
            		if boxes_c is None:
                		return( np.array([]),np.array([]) )    
            		rnet_time = time.time() - start_time

            	start_time = time.time()
		onet_time = 0
        	if self.onet:
            		boxes, boxes_c, landmark = self.outpute_faces(image, boxes_c)
            		if boxes_c is None:
                		return( np.array([]),np.array([]) )    
            		onet_time = time.time() - start_time
		return(boxes_c, landmark)


