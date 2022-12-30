import numpy as np
import scipy.io as scio
import copy
import os
import torch
from datetime import datetime
import argparse
import logger
from IOWMLayer_two import *
from torch.autograd import Variable

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # ignore warning

dtype = torch.FloatTensor
prev_time = datetime.now()
parser = argparse.ArgumentParser()
parser.add_argument('--data_path', type=str, default='./data/CHW_mat3755/')
parser.add_argument('--class_num', type=int, default=3755)
parser.add_argument('--num_epochs', type=int, default=50)
parser.add_argument('--batch_size', type=int, default=50)
parser.add_argument('--iter_threshold', type=int, default=10)
parser.add_argument('--add_epochs', type=int, default=3)
parser.add_argument('--immune_distance', type=int, default=5)
parser.add_argument('--device', type=str, default='cuda:1')
args = parser.parse_args()

device = args.device
class_num = args.class_num
num_epochs = args.num_epochs
batch_size = args.batch_size
data_path = args.data_path
iter_threshold = args.iter_threshold
add_epochs = args.add_epochs
immune_distance = args.immune_distance
Data_Path_train = os.path.join(data_path, 'train_each')
Data_Path_val = os.path.join(data_path, 'test_each')
print("device=", device, ' | num_epochs=', num_epochs, ' | data_path=',
      data_path, ' | class_num=', class_num, ' | iter_threshold=',
      iter_threshold, ' | add_epochs=', add_epochs, ' | immune_distance=', immune_distance)

def trans_onehot(index, batch_size_=200, class_num_=10):
    y = torch.LongTensor(batch_size_, 1).random_()
    if index.dim() == 1:
        index = index.unsqueeze(dim=1)
    y[:] = index
    y_onehot = torch.FloatTensor(batch_size_, class_num_)
    y_onehot.zero_()
    y_onehot.scatter_(1, y, 1)
    return y_onehot

def data_preprocessing(images, labels, train=True):
    length = len(images)
    if train:
        ss = np.arange(length)
        np.random.shuffle(ss)
        images = images[ss, :]
        labels = labels[ss, :]
    images = torch.Tensor(images)
    labels = torch.Tensor(labels)
    images = Variable(images.type(dtype), requires_grad=False).to(device)
    labels, _ = torch.max(labels, 1)
    labels = labels.type(torch.LongTensor)
    labels = trans_onehot(labels, labels.size(0), class_num)
    labels = labels.type(torch.LongTensor).to(device)
    return images, labels

def my_test(class_begin=0, class_end=class_num):
    correct = 0.0
    total = 0
    batch_size = 100
    for num_index in range(class_begin, class_end):
        mat_data = os.path.join(Data_Path_val, 'chwdata' + str(num_index))
        test = scio.loadmat(mat_data)
        testimages = test['test_data_each']
        testlabels = test['test_label_each']
        testlabels = testlabels.T
        test_length = len(testimages)
        testimages, testlabels = data_preprocessing(testimages, testlabels, train=False)

        for i in range(round(test_length / batch_size)):
            start = batch_size * i
            index_end = min(start + batch_size, test_length)
            batch_x = testimages[start:index_end, :]
            batch_y = testlabels[start:index_end, :]
            accu_all = OWM.predict_labels(batch_x, batch_y)
            accu_all = accu_all.numpy()
            total += np.shape(batch_x)[0]
            correct += accu_all
    test_accu = 100.0 * correct / total
    return test_accu

def epoch_train(epoch, num_epochs, batch_size, train_length, trainimages, trainlabels, num_index):
    for iters in range(epoch, num_epochs):
        # if iters == 0:
        #     immune = True
        # else:
        #     immune = False
        correct = 0.0
        total = 0
        for i in range(round(train_length / batch_size)):
            lamda = i / round(train_length / batch_size)
            start = batch_size * i
            index_end = min(start + batch_size, train_length)
            batch_x = trainimages[start:index_end, :]
            batch_y = trainlabels[start:index_end, :]
            lr_list = [2.0, 0.9 * 0.08 ** lamda, 0.8]
            OWM.owm_learn(batch_x, batch_y, lr_list, False)

            accu_all = OWM.predict_labels(batch_x, batch_y)
            accu_all = accu_all.numpy()
            total += np.shape(batch_x)[0]
            correct += accu_all
        train_acc = 100.0 * correct / (total * 1.0)
        Logger.append('[Train]|Task [{:d}/{:d}]: Epoch [{:d}/{:d}], Accuracy: {:.3f}'
                      .format(num_index + 1, class_num, iters + 1, 50, train_acc))
    return iters

lambda_loss = 0
middle = 4000
OWM = OWMLayer([[1024, middle], [middle, class_num]], alpha=[100.0, 100.0], l2_reg_lambda=lambda_loss, args=args)
Logger = logger.Logger('./CHW_IOWM.txt')
train_accs = []

for num_index in range(class_num):
    mat_data = os.path.join(Data_Path_train, 'chwdata' + str(num_index))
    train = scio.loadmat(mat_data)
    images = train['train_data_each']
    labels = train['train_label_each']
    labels = labels.T
    train_length = len(images)
    # trainimages, trainlabels = data_preprocessing(images, labels)
    batch_size = int(train_length) // 10
    accu_old = 0
    accu_all = 0
    flag_break = 0
    flag_iter = 0
    immune = False
    for epoch in range(num_epochs):
        trainimages, trainlabels = data_preprocessing(images, labels)
        correct = 0.0
        total = 0
        if epoch < immune_distance:
            immune = True
        else:
            immune = False
        for i in range(round(train_length / batch_size)):
            lamda = i / round(train_length / batch_size)
            start = batch_size * i
            index_end = min(start + batch_size, train_length)
            batch_x = trainimages[start:index_end, :]
            batch_y = trainlabels[start:index_end, :]
            lr_list = [2.0, 0.9 * 0.08 ** lamda, 0.8]
            loss = OWM.owm_learn(batch_x, batch_y, lr_list, immune)

            accu_all = OWM.predict_labels(batch_x, batch_y)
            accu_all = accu_all.numpy()
            total += np.shape(batch_x)[0]
            correct += accu_all
        train_acc = 100.0 * correct / (total * 1.0)
        Logger.append('[Train]|Task [{:d}/{:d}]: Epoch [{:d}/{:d}], Accuracy: {:.3f}'
                      .format(num_index + 1, class_num, epoch + 1, num_epochs, train_acc))

        accu_all = my_test(class_begin=num_index, class_end=num_index + 1)
        auc_delta = ((accu_all - accu_old) / (accu_old + 1e-8) * 100)
        if (1.0 >= auc_delta >= 0 or round(accu_all) == 100) and accu_all > 50:
            flag_break = 1
            if epoch + 1 <= iter_threshold:
                flag_iter = 1
                epoch = epoch_train(epoch + 1, epoch + 1 + add_epochs, batch_size, train_length, trainimages,
                                    trainlabels, num_index)
            Logger.append('Mat_number:[{:d}/{:d}], Epoch_number:[{:d}/{:d}],curr_acc:{:.2f} %'
                          .format(num_index + 1, class_num, epoch + 1, num_epochs, accu_all))
            train_accs.append(accu_all)
            break
        else:
            accu_old = copy.deepcopy(accu_all)
    if epoch + 1 <= iter_threshold and flag_iter == 0:
        epoch = epoch_train(epoch + 1, epoch + 1 + add_epochs, batch_size, train_length, trainimages, trainlabels,
                            num_index)
    if flag_break == 0:
        Logger.append('Mat_number:[{:d}/{:d}], Epoch_number:[{:d}/{:d}],curr_acc:{:.2f} %'
                      .format(num_index + 1, class_num, epoch + 1, num_epochs, accu_all))
        train_accs.append(accu_all)
# files = './data/IOWM/'
# if not os.path.exists(files):
#     os.makedirs(files)
#     print('Create path : {}'.format(files))
# train_accs = np.array(train_accs)
# # save the test_accs of every task in train process
# path = os.path.join(files, "each_task_train_test_accs.raw")
# train_accs.tofile(path)
accu_test = my_test(class_end=class_num)
Logger.append('All_acc:{:.2f} %'.format(accu_test))
cur_time = datetime.now()
h, remainder = divmod((cur_time - prev_time).seconds, 3600)
m, s = divmod(remainder, 60)
time_str = "Time %02d:%02d:%02d" % (h, m, s)
Logger.append(time_str)
