"""YOLO Meta-architecture definition.

General tensorflow implementation of YOLO models
"""
from abc import abstractmethod

import re
import tensorflow as tf

from object_detection.core import box_list
from object_detection.core import model
from object_detection.core import standard_fields as fields
from object_detection.utils import shape_utils
from object_detection.core import target_assigner

slim = tf.contrib.slim

class YOLOFeatureExtractor(object):
  """YOLO Feature Extractor definition"""

  def __init__(self,
               is_training,
               reuse_weights,):
    # TODO : find out the parameters
    self.is_training = is_training
    self.reuse_weights = reuse_weights
    pass
  
  @abstractmethod
  def preprocess(self, resized_inputs):
    """Preprocesses images for feature extraction (minus image resizing).

    Args:
      resized_inputs: a [batch, height, width, channels] float tensor
        representing a batch of images.

    Returns:
      preprocessed_inputs: a [batch, height, width, channels] float tensor
        representing a batch of images.
    """
    pass
  
  @abstractmethod
  def extract_features(self, preprocessed_inputs):
    """Extracts features from preprocessed inputs.

    This function is responsible for extracting the YOLO feature map from preprocessed
    images.

    Args:
      preprocessed_inputs: a [batch, height, width, channels] float tensor
        representing a batch of images.

    Returns:
      feature_maps: a tensor where the tensor has shape
        [batch, grid_size, grid_size, depth]
    """
    pass
  

class YOLOMetaArch(model.DetectionModel):
  """YOLO Meta Arch definition"""

  # TODO : Revisit which args are required and which are not
  # TODO : Add no object and obj loss in these params
  def __init__(self,
              is_training,
              box_coder,
              feature_extractor,
              matcher,
              num_classes,
              region_similarity_calculator,
              image_resizer_fn,
              non_max_suppression_fn,
              score_conversion_fn,
              classification_loss,
              localization_loss,
              object_loss,
              noobject_loss,
              classification_loss_weight,
              localization_loss_weight,
              object_loss_weight,
              noobject_loss_weight,
              hard_example_miner,
              add_summaries=True):
    """YOLOMetaArch Constructor

    Args:
      is_training: A boolean indicating whether the training version of the
        computation graph should be constructed.
      box_coder: a box_coder.BoxCoder object.
      feature_extractor: a YOLOFeatureExtractor object.
      matcher: a matcher.Matcher object.
      region_similarity_calculator: a
        region_similarity_calculator.RegionSimilarityCalculator object.
      image_resizer_fn: a callable for image resizing.  This callable always
        takes a rank-3 image tensor (corresponding to a single image) and
        returns a rank-3 image tensor, possibly with new spatial dimensions.
        See builders/image_resizer_builder.py.
      non_max_suppression_fn: batch_multiclass_non_max_suppression
        callable that takes `boxes`, `scores` and optional `clip_window`
        inputs (with all other inputs already set) and returns a dictionary
        hold tensors with keys: `detection_boxes`, `detection_scores`,
        `detection_classes` and `num_detections`. See `post_processing.
        batch_multiclass_non_max_suppression` for the type and shape of these
        tensors.
      score_conversion_fn: callable elementwise nonlinearity (that takes tensors
        as inputs and returns tensors).  This is usually used to convert logits
        to probabilities.
      classification_loss: an object_detection.core.losses.Loss object.
      localization_loss: a object_detection.core.losses.Loss object.
      classification_loss_weight: float
      localization_loss_weight: float
      hard_example_miner: a losses.HardExampleMiner object (can be None)
      add_summaries: boolean (default: True) controlling whether summary ops
        should be added to tensorflow graph.
      
    """
    super(YOLOMetaArch, self).__init__(num_classes=num_classes)
    self._is_training = is_training
    
    # Needed for fine-tuning from classification checkpoints whose
    # variables do not have the feature extractor scope.
    self._extract_features_scope = 'FeatureExtractor'

    self._box_coder = box_coder
    self._feature_extractor = feature_extractor
    self._matcher = matcher
    self._region_similarity_calculator = region_similarity_calculator

    unmatched_cls_target = None
    unmatched_cls_target = tf.constant([1] + self.num_classes * [0], tf.float32)
    self._target_assigner = target_assigner.TargetAssigner(
        self._region_similarity_calculator,
        self._matcher,
        self._box_coder,
        positive_class_weight=1.0,
        negative_class_weight=1.0,
        unmatched_cls_target=unmatched_cls_target)

    self._classification_loss = classification_loss
    self._localization_loss = localization_loss
    self._object_loss = object_loss
    self._noobject_loss = noobject_loss
    self._classification_loss_weight = classification_loss_weight
    self._localization_loss_weight = localization_loss_weight
    self._object_loss_weight = object_loss_weight
    self._noobject_loss_weight = noobject_loss_weight
    self._hard_example_miner = hard_example_miner

    self._image_resizer_fn = image_resizer_fn
    self._non_max_suppression_fn = non_max_suppression_fn
    self._score_conversion_fn = score_conversion_fn

    self._add_summaries = add_summaries

  def preprocess(self, inputs):
    """Feature-extractor specific preprocessing.

    See base class.

    Args:
      inputs: a [batch, height_in, width_in, channels] float tensor representing
        a batch of images with values between 0 and 255.0.

    Returns:
      preprocessed_inputs: a [batch, height_out, width_out, channels] float
        tensor representing a batch of images.
    Raises:
      ValueError: if inputs tensor does not have type tf.float32
    """
    if inputs.dtype is not tf.float32:
      raise ValueError('`preprocess` expects a tf.float32 tensor')
    with tf.name_scope('Preprocessor'):
      # TODO: revisit whether to always use batch size as  the number of
      # parallel iterations vs allow for dynamic batching.
      resized_inputs = tf.map_fn(self._image_resizer_fn,
                                 elems=inputs,
                                 dtype=tf.float32)
      return self._feature_extractor.preprocess(resized_inputs)

  def predict(self, preprocessed_inputs):
    """Predicts unpostprocessed tensors from input tensor.

    This function takes an input batch of images and runs it through the forward
    pass of the network to yield unpostprocessesed predictions.

    Args:
      preprocessed_inputs: a [batch, height, width, channels] image tensor.
    Returns:
      prediction_dict: a dictionary holding prediction tensors with
        1) class_predictions : 4-D float tensor of shape [batch_size,
          grid_size * grid_size * boxes_per_cell, 1, num_classes] containing
           the conditional class probabilities for each grid cell
        2) box_scores : 4-D float tensor of shape [batch_size,
           grid_size * grid_size * boxes_per_cell, 2, 1] containing the confidence scores
           of each predicted box
        3) detection_boxes : 4-D float tensor of shape [batch_size,
          grid_size * grid_size * boxes_per_cell, 1, 4] containing the co-ordinates of
          the predicted bounding boxes
    """
    with tf.variable_scope(None, self._extract_features_scope,
                           [preprocessed_inputs]):
      feature_map = self._feature_extractor.extract_features(
          preprocessed_inputs)

    combined_shape = shape_utils.combined_static_and_dynamic_shape(feature_map)
    batch_size = combined_shape[0]
    boxes_per_cell = (combined_shape[-1] - self._num_classes) / 5

    # Extract the required values
    class_predictions = feature_map[:, :, :, 0 : self._num_classes]
    box_scores = feature_map[:, :, :, self._num_classes : self._num_classes + boxes_per_cell]
    detection_boxes = feature_map[:, :, :, self._num_classes + boxes_per_cell :]

    # These three variables have shapes [batch_size, grid_size, grid_size, X]
    # Reshape each of these to [batch_size, grid_size * grid_size * boxes_per_cell, X]
    class_predictions = tf.reshape(class_predictions, [batch_size, -1, 1, self.num_classes])
    box_scores = tf.reshape(box_scores, [batch_size, -1, 2, 1])
    detection_boxes = tf.reshape(detection_boxes, [batch_size, -1, 1, 4])

    # class, confidence scores, bounding box coordinates

    predictions_dict = {
        'class_predictions' : class_predictions,
        'box_scores' : box_scores,
        'detection_boxes' : detection_boxes,
    }
    return predictions_dict

  def postprocess(self, prediction_dict):
    """Converts prediction tensors to final detections.

    This function converts raw predictions tensors to final detection results by
    slicing off the background class, decoding box predictions and applying
    non max suppression and clipping to the image window.

    See base class for output format conventions.  Note also that by default,
    scores are to be interpreted as logits, but if a score_conversion_fn is
    used, then scores are remapped (and may thus have a different
    interpretation).

    Args:
      prediction_dict: a dictionary holding prediction tensors with
        1) class_predictions : 4-D float tensor of shape [batch_size,
          grid_size * grid_size * boxes_per_cell, 1, num_classes] containing the conditional class
          probabilities for each grid cell
        2) box_scores : 4-D float tensor of shape [batch_size,
          grid_size * grid_size * boxes_per_cell, 2, 1] containing the confidence scores of each predicted box
        3) detection_boxes : 4-D float tensor of shape [batch_size,
          grid_size * grid_size * boxes_per_cell, 1, 4] containing the co-ordinates of
          the predicted bounding boxes

    Returns:
      detections: a dictionary containing the following fields
        detection_boxes: [batch, max_detection, 4]
        detection_scores: [batch, max_detections]
        detection_classes: [batch, max_detections]
        num_detections: [batch]
    Raises:
      ValueError: if prediction_dict does not contain 'box_class_encodings' fields.
    """
    if ('class_predictons' not in prediction_dict) or ('box_scores' not in prediction_dict) \
            or ('detection_boxes' not in prediction_dict):
      raise ValueError('prediction_dict does not contain expected entries.')
    with tf.name_scope('Postprocessor'):

      class_predictions = prediction_dict['class_predictions']
      box_scores = prediction_dict['box_scores']
      detection_boxes = prediction_dict['detection_boxes']

      combined_shape = shape_utils.combined_static_and_dynamic_shape(class_predictions)
      batch_size = combined_shape[0]

      # multiply class conditional probabilities with box confidences
      class_predictions = tf.multiply(box_scores, class_predictions)
      # reshape class probabilities as required by non-max suppression
      class_predictions = tf.reshape(class_predictions, [batch_size, -1, self._num_classes])
      detection_scores = self._score_conversion_fn(
          class_predictions)
      clip_window = tf.constant([0, 0, 1, 1], tf.float32)
      (nmsed_boxes, nmsed_scores, nmsed_classes, _,
       num_detections) = self._non_max_suppression_fn(detection_boxes,
                                                      detection_scores,
                                                      clip_window=clip_window)
      return {'detection_boxes': nmsed_boxes,
              'detection_scores': nmsed_scores,
              'detection_classes': nmsed_classes,
              'num_detections': tf.to_float(num_detections)}

  def loss(self, prediction_dict, scope=None):
    """Compute scalar loss tensors with respect to provided groundtruth.

    Calling this function requires that groundtruth tensors have been
    provided via the provide_groundtruth function.

    Args:
      prediction_dict: a dictionary holding prediction tensors with
        1) class_predictions : 4-D float tensor of shape [batch_size,
          grid_size * grid_size * boxes_per_cell, 1, num_classes] containing the conditional class
          probabilities for each grid cell
        2) box_scores : 4-D float tensor of shape [batch_size,
          grid_size * grid_size * boxes_per_cell, 2, 1] containing the confidence scores of each predicted box
        3) detection_boxes : 4-D float tensor of shape [batch_size,
          grid_size * grid_size * boxes_per_cell, 1, 4] containing the co-ordinates of
          the predicted bounding boxes

    Returns:
      a dictionary mapping loss keys (`localization_loss`, `classification_loss`,
      `object loss` and 'noobj loss`) to scalar tensors representing corresponding
       loss values.
    """
    class_predictions = prediction_dict['class_predictions']
    box_scores = prediction_dict['box_scores']
    detection_boxes = prediction_dict['detection_boxes']

    with tf.name_scope(scope, 'Loss', prediction_dict.values()):
      (batch_cls_targets, batch_cls_weights, batch_reg_targets,
       batch_reg_weights, match_list) = self._assign_yolo_targets(
           self.groundtruth_lists(fields.BoxListFields.boxes),
           self.groundtruth_lists(fields.BoxListFields.classes),
           detection_boxes,)

      # TODO: what is summarize_input() ?
      #if self._add_summaries:
      #  self._summarize_input(
      #      self.groundtruth_lists(fields.BoxListFields.boxes), match_list)

      num_matches = tf.stack(
          [match.num_matched_columns() for match in match_list])
      location_losses = self._localization_loss(
          prediction_dict['box_encodings'],
          batch_reg_targets,
          weights=batch_reg_weights)
      cls_losses = self._classification_loss(
          prediction_dict['class_predictions'],
          batch_cls_targets,
          weights=batch_cls_weights)
      obj_losses = self._object_loss(
          prediction_dict['confidence_scores'],
          batch_cls_targets,
          weights=batch_cls_weights)
      noobj_losses = self._noobject_loss(
          prediction_dict['confidence_scores'],
          batch_cls_targets,
          weights=batch_cls_weights)

      # Optionally apply hard mining on top of loss values
      localization_loss = tf.reduce_sum(location_losses)
      classification_loss = tf.reduce_sum(cls_losses)
      object_loss = tf.reduce_sum(obj_losses)
      noobject_loss = tf.reduce_sum(noobj_losses)
      if self._hard_example_miner:
        (localization_loss, classification_loss, object_loss, noobject_loss) = self._apply_hard_mining(
            location_losses, cls_losses, obj_losses, noobj_losses, prediction_dict, match_list)
        if self._add_summaries:
          self._hard_example_miner.summarize()

      # Optionally normalize by number of positive matches
      normalizer = tf.constant(1.0, dtype=tf.float32)
      if self._normalize_loss_by_num_matches:
        normalizer = tf.maximum(tf.to_float(tf.reduce_sum(num_matches)), 1.0)

      loss_dict = {
          'localization_loss': (self._localization_loss_weight / normalizer) *
                               localization_loss,
          'classification_loss': (self._classification_loss_weight /
                                  normalizer) * classification_loss,

          'object_loss': (self._object_loss_weight /
                                  normalizer) * object_loss,

          'noobject_loss': (self._noobject_loss_weight /
                                  normalizer) * noobject_loss
      }
    return loss_dict


  def _assign_yolo_targets(self, groundtruth_boxes_list, groundtruth_classes_list, detection_boxes):
    # TODO fix returns
    """Assign groundtruth targets.

    Used to obtain regression and classification targets.

    Args:
      groundtruth_boxes_list: a list of 2-D tensors of shape [num_boxes, 4]
        containing coordinates of the groundtruth boxes.
          Groundtruth boxes are provided in [y_min, x_min, y_max, x_max]
          format and assumed to be normalized and clipped
          relative to the image window with y_min <= y_max and x_min <= x_max.
      groundtruth_classes_list: a list of 2-D one-hot (or k-hot) tensors of
        shape [num_boxes, num_classes] containing the class targets with the 0th
        index assumed to map to the first non-background class.
      detection_boxes: 4-D float tensor of shape [batch_size,
        grid_size * grid_size * boxes_per_cell, 1, 4] containing the co-ordinates of
        the predicted bounding boxes
    Returns:
      batch_cls_targets: a tensor with shape [batch_size, num_anchors,
        num_classes],
      batch_cls_weights: a tensor with shape [batch_size, num_anchors],
      batch_reg_targets: a tensor with shape [batch_size, num_anchors,
        box_code_dimension]
      batch_reg_weights: a tensor with shape [batch_size, num_anchors],
      match_list: a list of matcher.Match objects encoding the match between
        anchors and groundtruth boxes for each image of the batch,
        with rows of the Match objects corresponding to groundtruth boxes
        and columns corresponding to anchors.
    """

    # list of box lists where each box list contains ground truths for each image in a batch
    groundtruth_boxlists = [box_list.BoxList(boxes)
                            for boxes in self.groundtruth_lists(fields.BoxListFields.boxes)]

    # TODO: avoid hard coding model dimensions in future
    S = 7  # grid size
    B = 2  # bounding boxes per grid cell
    image_size = 448  # image size

    # for each image create a list containing grid_size * grid_size
    # lists where each inner list is a list of ground truths of that
    # image in a particular grid cell
    # the final dimension of this list will be [batch_size, S*S, box_list_size]
    responsibility_list_batch = []

    for image_boxlist in groundtruth_boxlists:
      grid_cell_responsibilities = [[] * (S * S)]

      ycenter, xcenter = image_boxlist.get_center_coordinates_and_sizes()[: 2]
      ycenter /= image_size
      ycenter *= S
      ycenter = tf.cast(ycenter, tf.int32)

      xcenter /= image_size
      xcenter *= S
      xcenter = tf.cast(xcenter, tf.int32)

      # grid_cell_index[i] is the grid cell in which the i'th ground truth is located
      grid_cell_index = xcenter * S + ycenter

      # list of tensor objects corresponding to each ground truth box
      boxes = tf.unstack(image_boxlist.get())

      # push each ground truth into the correct place
      num_boxes = len(boxes)
      for i in xrange(num_boxes):
        grid_cell_responsibilities[grid_cell_index[i]].append(boxes[i])

      for i in xrange(S * S):
        grid_cell_responsibilities[i] = box_list.BoxList(tf.stack(grid_cell_responsibilities[i]))

      responsibility_list_batch.append(grid_cell_responsibilities)


    # TODO unstack  predictions using tf.unstack
    # TODO convert this into a list of box lists


    detection_boxes_unstacked = tf.unstack(detection_boxes)

    # the final dimension of this list will be [batch_size, S*S, box_list_size]
    prediction_box_list_batch = []

    for plist in detection_boxes_unstacked:
      unstacked_plist = tf.unstack(plist)
      # TODO conver detection_boxes to xmin ymin xmax ymax

      prediction_box_list = [box_list.BoxList(boxes) for boxes in unstacked_plist]
      
      assert len(prediction_box_list) == S * S

      prediction_box_list_batch.append((prediction_box_list))

    # TODO run matcher.py for each index i of the grid cells

    # batch sizes of the two lists should be the same
    assert len(responsibility_list_batch) == len(prediction_box_list_batch)
    num_batches = len(responsibility_list_batch)


    # TODO resume here
    I_ij_obj_list_batch = []

    # TODO run a loop to generate a list corresponding to I_ij^OBJ
    for batch_num in xrange(num_batches):
      I_ij_obj_list = []

      for i in xrange(S*S):
        list1 = responsibility_list_batch[batch_num][i]
        list2 = prediction_box_list_batch[batch_num][i]

        matchObject = self._matcher(self._region_similarity_calculator(list1, list2))
        I_ij_obj_list.append(matchObject.matched_column_indicator())

        # TODO permute the ground truth data and convert xmin ymin, to xc and yc

      I_ij_obj_list_batch.append(I_ij_obj_list)


    # TODO when computing losses, use tf.stack to convert list to a tensor
    # TODO scale the co-ordinates of the bounding boxes appropriately
    # TODO similarly, generate indicator variables for the confidence and I_i^OBJ
    # TODO tada.mpg

    # TODO Convert predicted bounding boxes to a box list
    # TODO Compute IOU matrix for every grid cell
    # TODO Apply matcher for every grid cell and obtain required indicators


  def restore_map(self, from_detection_checkpoint=True):
    """Returns a map of variables to load from a foreign checkpoint.

    See parent class for details.

    Args:
      from_detection_checkpoint: whether to restore from a full detection
        checkpoint (with compatible variable names) or to restore from a
        classification checkpoint for initialization prior to training.

    Returns:
      A dict mapping variable names (to load from a checkpoint) to variables in
      the model graph.
    """
    variables_to_restore = {}
    for variable in tf.all_variables():
      if variable.op.name.startswith(self._extract_features_scope):
        var_name = variable.op.name
        if not from_detection_checkpoint:
          var_name = (re.split('^' + self._extract_features_scope + '/',
                               var_name)[-1])
        variables_to_restore[var_name] = variable
    return variables_to_restore

