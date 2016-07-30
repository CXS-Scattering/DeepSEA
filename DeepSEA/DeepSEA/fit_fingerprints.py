#!/usr/bin/env python
# -*- tab-width:4;indent-tabs-mode:f;show-trailing-whitespace:t;rm-trailing-spaces:t -*-
# vi: set ts=4 et sw=4:

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import time
import tensorflow as tf
import numpy as np

from six.moves import xrange  # pylint: disable=redefined-builtin

from DeepSEA.util import (
	rmse,
)

from DeepSEA.queue_substances import (
	train_substances_network,
	validate_substances_network,
	test_substances_network,
)

from DeepSEA.model import (
	initialize_variables,
	build_summary_network,
	build_fps_network,
	build_normed_prediction_network,
	build_loss_network,
	build_optimizer,
)


def eval_in_batches(sess, coord, threads, predictions, labels, n_batches):
	predictions_eval = []
	labels_eval = []
	try:
		for step in xrange(n_batches):
			if coord.should_stop(): break
			p, l = sess.run(fetches=[predictions, labels])
			predictions_eval.append(p)
			labels_eval.append(l)
	except tf.errors.OutOfRangeError:
		pass

	predictions_eval = np.concatenate(predictions_eval)
	labels_eval = np.concatenate(labels_eval)
	return predictions_eval, labels_eval



def fit_fingerprints(
	task_params,
	model_params,
	train_params):

	if task_params['verbose']:
		print("Building fingerprint function of length {fp_length} as a convolutional network with width {fp_width} and depth {fp_depth} ...".format(**model_params))

	with tf.device(task_params['device']):
		variables = initialize_variables(train_params, model_params)

		train_substances, train_labels = train_substances_network(train_params, task_params)
		train_fps = build_fps_network(train_substances, variables, model_params)
		train_normed_predictions = build_normed_prediction_network(
			train_fps, variables, model_params)
		train_predictions, train_loss = build_loss_network(
			train_normed_predictions, train_labels, variables, model_params)
		optimizer = build_optimizer(train_loss, train_params)

		validate_substances, validate_labels = validate_substances_network(train_params, task_params)
		validate_fps = build_fps_network(validate_substances, variables, model_params)
		validate_normed_predictions = build_normed_prediction_network(
			validate_fps, variables, model_params)
		validate_predictions, validate_loss = build_loss_network(
			validate_normed_predictions, validate_labels, variables, model_params)

		test_substances, test_labels = test_substances_network(train_params, task_params)
		test_fps = build_fps_network(test_substances, variables, model_params)
		test_normed_predictions = build_normed_prediction_network(
			test_fps, variables, model_params)
		test_predictions, test_loss = build_loss_network(
			test_normed_predictions, test_labels, variables, model_params)


		train_summary = build_summary_network(train_loss)

	if task_params['verbose']:
		print("Loading data from '{train_substances_fname}'\n".format(**task_params))

	if task_params['verbose']:
		print("Begin Tensorflow session ...")
	start_time = time.time()

	training_loss_curve = []
	training_rmse_curve = []
	validate_rmse_curve = []

	session_config = tf.ConfigProto(
		allow_soft_placement=True,
		log_device_placement=False)

	with tf.Session(config=session_config) as sess:
		sess.run(tf.initialize_all_variables())
		sess.run(tf.initialize_local_variables())
		coord = tf.train.Coordinator()
		threads = tf.train.start_queue_runners(sess=sess, coord=coord)

		if task_params['verbose']:
			print("Initalized tensorflow session ...")


		train_writer = tf.train.SummaryWriter(task_params['summaries_dir'] + '/train', sess.graph)
		test_writer = tf.train.SummaryWriter(task_params['summaries_dir'] + '/test')

		try:
			for train_step in xrange(train_params['train_substances_n_batches']):
				if coord.should_stop(): break

				_, loss, predictions, labels, summary = sess.run(
					fetches=[optimizer, train_loss, train_predictions, train_labels, train_summary])

				training_loss_curve += [loss]
				train_rmse = rmse(predictions, labels)
				training_rmse_curve += [train_rmse]
				test_writer.add_summary(summary, train_step)

				if train_step % train_params['validate_frequency'] == 0:

					elapsed_time = time.time() - start_time
					start_time = time.time()
					print('Minibatch %d: %.1f ms' %
						(train_step, 1000 * elapsed_time / train_params['validate_frequency']))
					print('Minibatch loss: %.3f' % (loss))
					print('Minibatch RMSE: %.1f' % train_rmse)

					with tf.device(task_params['device']):
						validate_predictions_eval, validate_labels_eval = eval_in_batches(
							sess, coord, threads,
							validate_predictions, validate_labels,
							train_params['validate_substances_n_batches'])

					validate_rmse = rmse(validate_predictions_eval, validate_labels_eval)
					validate_rmse_curve += [validate_rmse]
					print('Validate RMSE: %.1f' % validate_rmse)
					print("")
				else:
					validate_rmse_curve += [None]
		except tf.errors.OutOfRangeError:
			pass

		with tf.device(task_params['device']):
			test_predictions_eval, test_labels_eval = eval_in_batches(
				sess, coord, threads,
				test_predictions, test_labels,
				train_params['test_substances_n_batches'])

		test_rmse = rmse(test_predictions_eval, test_labels_eval)
		print('Test RMSE: %.1f' % test_rmse)

		if task_params['verbose']:
			print("Complete returning ... ")

		return training_loss_curve, training_rmse_curve, validate_rmse_curve