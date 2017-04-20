'''
Get a regression model to get the right prediction. 

Version 0.1: Line Regression, treat one label's radar maps as X (4 * 15 * 101 * 101),

Compress X to 101 * 101, in other words, get the mean of radar maps of one label.

    yhat = aXb + c
    (
        yhat.shape = (),
        X.shape = (101, 101)
        a.shape = (1, 101)
        b.shape = (101, 1)
        c.shape = ()
    )
    
    Loss = l2 loss of yhat and y.
    
Author: Minquan Gao
Data: 17-Apr-19
'''

import tensorflow as tf
import numpy as np
import itertools
import evalution
import pickle
import os
import draw_performance
import time

EMOJIS = ['\U0001f601', '\U0001f602', '\U0001f603', '\U0001f604']


class Config:
    learning_rate = 2 * 1e-2 # learning_rate
    regularization_rate = 1e-3 # regularization rate
    batch_size = 256
    epoch = 100
    x_size = 101 * 101
    train_data_size = 2000

    TIME = 15
    HEIGHT = 4

    hidden_size = 20


np.random.seed(0)


class RainRegression:
    def __init__(self, test=True):
        self.config = Config()
        self.X_dimension = self.config.x_size
        self.__add_model()

        self.train_indices, self.validation_indices, self.test_indices = self.split_test_train()

        if test:
            self.config.train_data_size = 128
            self.train_indices = self.train_indices[: self.config.batch_size]
            self.config.epoch = 2

        self.cache = self.__load_data()

        assert len(self.train_indices) / self.config.batch_size >= 1

    def __load_data(self):
        '''
        Loads data in memory to speed up the calculate time.
        :return: 
        '''
        indices = np.concatenate([self.train_indices, self.test_indices, self.validation_indices])

        data_cache = {}

        file_dir = './pickle'
        for i, index in enumerate(indices):
            target_train_file = os.path.join(file_dir, 'train_{}.pickle'.format(index))
            try:
                with open(target_train_file, 'rb') as f:
                    data = pickle.load(f)
                    label = float(data['label'])
                    radar_maps = data['radar_maps']

                    compressed_radar_maps = self.compress_radar_maps(radar_maps)

                    data_cache[index] = (label, compressed_radar_maps)
            except EOFError as e:
                print('{} eof error'.format(target_train_file))
                return None, None
            finally:
                print('.', end='')
                if i % 100 == 0: print('')

        print('Data Load Finished.')

        return data_cache


    def __add_model(self):

        FC_LAYER_1 = 'fc_layer_1'
        FC_LAYER_2 = 'fc_layer_2'

        with tf.variable_scope('train_data') as scope:
            self.X_train = tf.placeholder(tf.float32, shape=(None, self.X_dimension))
            self.labels = tf.placeholder(tf.float32, shape=(None, ))

        with tf.variable_scope(FC_LAYER_1) as fc_scope:
            weights_1 = tf.get_variable(name='weight_1', shape=(self.X_dimension, 1),
                                             initializer=tf.truncated_normal_initializer(stddev=0.02))

            bias_1 = tf.get_variable(name='bias_1', shape=(),
                                          initializer=tf.constant_initializer(0.0))

        with tf.variable_scope(FC_LAYER_1, reuse=True) as fc_scope:
            fc_scope.reuse_variables()
            layout_1_output = tf.abs(tf.matmul(self.X_train, weights_1) + bias_1)

        with tf.variable_scope('tanh_1') as relu_scope:
            tanh_output = tf.tanh(layout_1_output)

        with tf.variable_scope(FC_LAYER_2) as fc_2_scope:
            a = tf.get_variable(name='a', shape=(), initializer=tf.truncated_normal_initializer(stddev=0.02))
            b = tf.get_variable(name='b', shape=(), initializer=tf.zeros_initializer())

            layout_2_output = tf.abs(a * tanh_output + b)

        # with tf.variable_scope('relu_layer_1') as relu_scope:
        #     self.layout_1_output = tf.nn.relu(self.layout_1_output)
        #
        # output: S * X
        #
        # with tf.variable_scope('linear_layer_2') as linear_scope_2:
        #     self.a = tf.Variable(tf.truncated_normal(shape=(self.config.hidden_size, 1), stddev=0.02))
        #     self.b = tf.Variable(tf.zeros(shape=()))
        #

        need_regularize = [weights_1, bias_1, a, b]

        l2_loss = sum(map(lambda w: tf.nn.l2_loss(w), need_regularize))

        tf.add_to_collection(name='l2_loss', value=l2_loss)

        with tf.variable_scope('get_value') as predict:
            self.yhat = layout_2_output
            # self.yhat = tf.matmul(self.layout_1_output, self.a) + self.b

        with tf.variable_scope('loss') as loss_scope:
            self.loss = self.loss(self.yhat)

        with tf.variable_scope('op') as op_scope:
            # op_scope.reuse_variables()
            self.op = self.optimizer(self.loss)

    def split_test_train(self):
        '''
        Split train dataset to train, validation, test 
        :return: [train_indices], [validation_indices], [test_indices]
        '''

        shuffled_indices = np.random.choice(np.random.permutation(range(1, 10000)), self.config.train_data_size)


        test_ratio = 0.15
        train_ratio = (1 - test_ratio) * .8
        validation_ratio = (1 - test_ratio) * .2

        train_num = int(self.config.train_data_size * train_ratio)
        validation_num = int(self.config.train_data_size * validation_ratio)
        test_num = int(self.config.train_data_size * test_ratio)

        train_indices = shuffled_indices[0: train_num]
        validation_indices = shuffled_indices[train_num: train_num + validation_num]
        test_indices = shuffled_indices[-1 * test_num: ]

        return train_indices, validation_indices, test_indices

    def train_one_epoch(self, sess):
        '''
        Train one epoch, run 10000/batch_size time, each time use the train data with bath_size.
        :return: loss value
        '''

        total_batches = int(len(self.train_indices) / self.config.batch_size)

        losses = []
        RMSEs = []
        val_RMSEs = []

        for b in range(total_batches):
            indices = np.random.choice(self.train_indices,
                                       self.config.batch_size,
                                       replace=True)

            train_data, train_labels = self.get_data_by_indices(indices)

            if train_data is None:
                print('training data error, skip this batch')
                continue

            feed_dict = {self.X_train: train_data, self.labels: train_labels}

            # bias = self.bias_1.eval()
            # print('bias before training is: {}'.format(bias))

            L, _, labels, yhat = sess.run(
                [self.loss, self.op, self.labels, self.yhat],
                feed_dict=feed_dict
            )

            # bias = self.bias_1.eval()

            # print('bias: {}'.format(bias))

            losses.append(L)

            y = train_labels
            yhat = self.predict(train_data, sess)

            RMSE_score = self.accuracy(y=y, yhat=yhat)
            RMSEs.append(RMSE_score)

            val_accuracy = self.validation_accuracy(sess)

            val_RMSEs.append(val_accuracy)

            if b % 10 == 0:
                print('')
                print('batching {}/{}'.format(b, total_batches))
                print('train loss: {}'.format(L))
                print('train RMSE score: {}'.format(RMSE_score))
                print('validation RMSE score: {}'.format(val_accuracy))
                print('')
            else:
                print('.', end='')

        return sum(losses)/len(losses), sum(RMSEs)/len(RMSEs), sum(val_RMSEs)/len(val_RMSEs)

    def validation_accuracy(self, sess):
        validation_data, validation_labels = self.get_data_by_indices(self.validation_indices)
        y = validation_labels
        yhat = self.predict(validation_data, sess)
        return self.accuracy(y=y, yhat=yhat)

    def get_data_by_indices(self, indices):

        assert (len(indices) == self.config.batch_size) or (len(indices) == len(self.validation_indices))

        train_data = np.zeros(shape=(len(indices), self.X_dimension))
        train_labels = np.zeros(shape=(len(indices),))

        for i, index in enumerate(indices):
            train_data[i,:] = self.cache[index][1]
            train_labels[i] = self.cache[index][0]

        return train_data, train_labels

    # @staticmethod
    # def mean_radar_maps(radar_maps):
    #     mean = np.mean(radar_maps, axis=1)
    #     compressed = mean.flatten()
    #
    #     return compressed

    @staticmethod
    def compress_radar_maps(radar_maps):
        mean = np.mean(radar_maps, axis=(0, 1))
        compressed = mean.flatten()

        return compressed

    def train(self):
        avg_losses = []
        avg_RMSEs = []
        avg_val_RMSEs = []

        init = tf.global_variables_initializer()

        with tf.Session() as sess:
            sess.run(init)

            for ep in range(self.config.epoch):
                start = time.time()
                print('*'*8)
                print(np.random.choice(EMOJIS)+'  epoch: {}'.format(ep))
                avg_loss, avg_rmse, avg_val_rmse = self.train_one_epoch(sess)
                print(np.random.choice(EMOJIS)+'  epoch loss: {}'.format(avg_loss))
                print(np.random.choice(EMOJIS)+'  epoch RMSE: {}'.format(avg_rmse))
                print(np.random.choice(EMOJIS)+'  epoch validation RMSE: {}'.format(avg_val_rmse))
                avg_losses.append(avg_loss)
                avg_RMSEs.append(avg_rmse)
                avg_val_RMSEs.append(avg_val_rmse)

                end = time.time()

                print(np.random.choice(EMOJIS)+'  Total Time: {}'.format(end - start))

        print('done!')

        return avg_losses, avg_RMSEs, avg_val_RMSEs

    def predict(self, test_X, sess):
        yhat = sess.run([self.yhat], feed_dict={self.X_train: test_X})
        return yhat

    def loss(self, yhat):
        loss_mse = tf.nn.l2_loss(yhat - self.labels)
        l2_loss = tf.get_collection('l2_loss')[0]
        L = loss_mse + self.config.regularization_rate * l2_loss

        return L

    def optimizer(self, L):
        global_step = tf.Variable(0, trainable=True)
        starter_learning_rate = self.config.learning_rate
        # learning_rate = starter_learning_rate
        learning_rate = tf.train.exponential_decay(starter_learning_rate, global_step,
                                                   10000, 0.96, staircase=True)

        op = tf.train.AdamOptimizer(learning_rate=learning_rate).minimize(loss=L)

        return op

    def accuracy(self, y, yhat):
        return evalution.RMSE(y, yhat)


def dtest():
    rain_regression = RainRegression()

    print('start testing')

    assert rain_regression is not None

    test_radar_maps = np.zeros(shape=(15, 4, 101, 101))

    random_numbers = []
    # for i, j in itertools.product(range(15), range(4)):
    #     random_num = np.random.randint(100)
    #     test_radar_maps[i][j][0][0] = random_num
    #     random_numbers.append(random_num)
    #
    # compressed_radar = rain_regression.mean_radar_maps(test_radar_maps)
    #
    # assert compressed_radar[0] == np.mean(np.array(random_numbers))

    # loss, RMSE, valRMSE = rain_regression.train_one_epoch()
    #
    # assert isinstance(loss, float)


    epoch_losses = rain_regression.train()

    assert epoch_losses is not None
    assert isinstance(epoch_losses[0][0], float)

    del rain_regression

    print('test done!')

# dtest()

if __name__ == '__main__':
    print('begin training..')
    rain_regression = RainRegression(test=False)
    losses, RMSEs, val_RMSE = rain_regression.train()
    draw_performance.draw(losses, RMSEs, val_RMSE)