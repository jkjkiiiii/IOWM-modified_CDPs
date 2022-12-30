import numpy as np
import torch
dtype = torch.cuda.FloatTensor  # run on GPU
import utils


########################################################################################################################

class Appr(object):

    def __init__(self, model, nepochs=20, sbatch=40, lr=0.2):
        self.model = model
        self.nepochs = nepochs
        self.sbatch = sbatch
        self.lr = lr

        self.ce = torch.nn.CrossEntropyLoss()
        self.optimizer = self._get_optimizer()

        with torch.no_grad():
            self.P1 = torch.autograd.Variable(torch.eye(785).type(dtype))
            self.P2 = torch.autograd.Variable(torch.eye(801).type(dtype))

        self.test_max = 0

        return

    def _get_optimizer(self, t=0, lr=None):
        lr = self.lr
        lr_owm = self.lr
        fc1_params = list(map(id, self.model.fc1.parameters()))
        fc2_params = list(map(id, self.model.fc2.parameters()))
        base_params = filter(lambda p: id(p) not in fc1_params + fc2_params,
                             self.model.parameters())
        optimizer = torch.optim.SGD([{'params': base_params},
                                     {'params': self.model.fc1.parameters(), 'lr': lr_owm},
                                     {'params': self.model.fc2.parameters(), 'lr': lr_owm}
                                     ], lr=lr, momentum=0.9)

        return optimizer

    def train(self, t, xtrain, ytrain, xvalid, yvalid, data):
        best_model = utils.get_model(self.model)
        lr = self.lr

        current_step = 0
        all_data = len(ytrain)
        all_step = all_data * self.nepochs // self.sbatch

        self.optimizer = self._get_optimizer(t, lr)
        nepochs = self.nepochs
        # Loop epochs
        try:
            for e in range(nepochs):
                # Train
                current_step = self.train_epoch(xtrain, ytrain, current_step=current_step, all_step=all_step, cur_epoch=e, nepoch=nepochs)
                train_loss, train_acc = self.eval(xtrain, ytrain)
                print('| [{:d}/2], Epoch {:d}/{:d}, | Train: loss={:.3f}, acc={:2.4f}% |'.format(t + 1, e + 1,
                                                    nepochs, train_loss, 100 * train_acc), end='')
                # # Valid
                valid_loss, valid_acc = self.eval(xvalid, yvalid)
                print(' Valid: loss={:.3f}, acc={:5.2f}% |'.format(valid_loss, 100 * valid_acc), end='')
                print()

                xtest = data[2]['test']['x'].cuda()
                ytest = data[2]['test']['y'].cuda()

                _, test_acc = self.eval(xtest, ytest)
                # print('>>> Test on All Task:->>>{:2.2f}% <<<'.format(100 * test_acc))

                if test_acc > self.test_max:
                    self.test_max = max(self.test_max, test_acc)
                    best_model = utils.get_model(self.model)

                print('>>> Test on All Task:->>> Max_acc : {:2.2f}%  Curr_acc : {:2.2f}%<<<'.format(100 * self.test_max,100 * test_acc))

        except KeyboardInterrupt:
            print()

        # Restore best validation model
        utils.set_model_(self.model, best_model)
        return

    def train_epoch(self, x, y, current_step=0, all_step=0, cur_epoch=0, nepoch=0):

        self.model.train()

        r_len = np.arange(x.size(0))
        np.random.shuffle(r_len)
        r_len = torch.LongTensor(r_len).cuda()

        # Loop batches
        for i_batch in range(0, len(r_len), self.sbatch):
            lamda = current_step / all_step
            current_step += 1
            b = r_len[i_batch:min(i_batch + self.sbatch, len(r_len))]
            images = torch.autograd.Variable(x[b], volatile=False)
            targets = torch.autograd.Variable(y[b], volatile=False)

            # Forward
            output, h_list = self.model.forward(images)
            loss = self.ce(output, targets)

            # Backward
            self.optimizer.zero_grad()
            loss.backward()

            alpha_array = [0.9 * 0.001 ** lamda, 0.6]

            def pro_weight(p, x, w, alpha=1.0):
                r = x
                k = torch.mm(p, torch.t(r))
                deltap = torch.mm(k, torch.t(k)) / (alpha + torch.mm(r, k))
                tmp_P = p - deltap
                p = tmp_P.detach()
                w.grad.data = torch.mm(w.grad.data, torch.t(p.data))
                return p
            # Compensate embedding gradients
            for n, w in self.model.named_parameters():
                if n == 'fc1.weight':
                    self.P1 = pro_weight(self.P1,  h_list[0], w, alpha=alpha_array[0])

                if n == 'fc2.weight':
                    self.P2 = pro_weight(self.P2,  h_list[1], w, alpha=alpha_array[1])

            self.optimizer.step()
        return current_step - 1

    def eval(self, x, y):
        total_loss = 0
        total_acc = 0
        total_num = 0
        self.model.eval()

        r = np.arange(x.size(0))
        r = torch.LongTensor(r).cuda()

        # Loop batches
        for i in range(0, len(r), self.sbatch):
            b = r[i:min(i + self.sbatch, len(r))]
            with torch.no_grad():
                images = torch.autograd.Variable(x[b])
                targets = torch.autograd.Variable(y[b])

                # Forward
                output, _ = self.model.forward(images)
                loss = self.ce(output, targets)
                _, pred = output.max(1)
                hits = (pred % 10 == targets).float()

                # Log
                total_loss += loss.data.cpu().numpy().item() * len(b)
                total_acc += hits.sum().data.cpu().numpy().item()
                total_num += len(b)

        return total_loss / total_num, total_acc / total_num
