import os
import numpy as np
import torch
import torch.nn.functional as F

cuda = True if torch.cuda.is_available() else False
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def cal_sample_weight(labels, num_class, use_sample_weight=True):
    if not use_sample_weight:
        return np.ones(len(labels)) / len(labels)
    count = np.zeros(num_class)
    for i in range(num_class):
        count[i] = np.sum(labels==i)
    sample_weight = np.zeros(labels.shape)
    for i in range(num_class):
        sample_weight[np.where(labels==i)[0]] = count[i]/np.sum(count)
    
    return sample_weight


def one_hot_tensor(y, num_dim):
    y_onehot = torch.zeros(y.shape[0], num_dim)
    y_onehot.scatter_(1, y.view(-1,1), 1)
            #scatter_(input, dim, index, src)将src中数据根据index中的索引按照dim的方向填进input中.
    
    return y_onehot


def cosine_distance_torch(x1, x2=None, eps=1e-8): #余弦相似度
    x2 = x1 if x2 is None else x2
    w1 = x1.norm(p=2, dim=1, keepdim=True)
    w2 = w1 if x2 is x1 else x2.norm(p=2, dim=1, keepdim=True)
    return 1 - torch.mm(x1, x2.t()) / (w1 * w2.t()).clamp(min=eps)
    #将输入input张量每个元素的夹紧到区间 [min,max][min,max]，并返回结果到一个新张量。


def to_sparse(x):
    x_typename = torch.typename(x).split('.')[-1]
    sparse_tensortype = getattr(torch.sparse, x_typename)
    #getattr：getattr() 函数用于返回一个对象属性值
    indices = torch.nonzero(x)
    #torch.nonzero:返回x中所有非0的元素位置
    if len(indices.shape) == 0:  # if all elements are zeros
        return sparse_tensortype(*x.shape)
    indices = indices.t()
    #将tensor进行转置，即把所有非0的元素的行位置放在第0行，把所有非0的元素的列位置放在第1行
    values = x[tuple(indices[i] for i in range(indices.shape[0]))]
    #values为x中所有非0元素
    return sparse_tensortype(indices, values, x.size())


def cal_adj_mat_parameter(edge_per_node, data, metric="cosine"):
    assert metric == "cosine", "Only cosine distance implemented"
    dist = cosine_distance_torch(data, data) #计算余弦相似度
    parameter = torch.sort(dist.reshape(-1,)).values[edge_per_node*data.shape[0]]
    #dist.reshape(-1,):拉长为一维
    return parameter.data.cpu().numpy().item()
          #np.asscalar:将向量X转换成标量，且向量X只能为一维含单个元素的向量


def graph_from_dist_tensor(dist, parameter, self_dist=True):
    #只留下所有小于parameter值的位置，设为1，其余位置和对角线为0
    if self_dist:
        assert dist.shape[0]==dist.shape[1], "Input is not pairwise dist matrix"
    g = (dist <= parameter).float()
    if self_dist:
        diag_idx = np.diag_indices(g.shape[0])
        #返回索引以访问数组的主对角线
        g[diag_idx[0], diag_idx[1]] = 0
        
    return g


def gen_adj_mat_tensor(data, parameter, metric="cosine"):
    #parameter:adj_parameter_adaptive = cal_adj_mat_parameter(adj_parameter, data_tr_list[i], adj_metric)
    assert metric == "cosine", "Only cosine distance implemented"
    dist = cosine_distance_torch(data, data)
    g = graph_from_dist_tensor(dist, parameter, self_dist=True)
    if metric == "cosine":
        adj = 1.0-dist
    else:
        raise NotImplementedError
    adj = adj*g 
    adj_T = adj.transpose(0,1)
    #transpose：调换行列索引值，即求转置
    I = torch.eye(adj.shape[0])
    #torch.eye：生成对角线全1，其余部分全0的二维数组
    if cuda:
        I = I.cuda()
    adj = adj + adj_T*(adj_T > adj).float() - adj*(adj_T > adj).float()
    #tensor的*：两个tensor相同位置元素相乘，无关于其他元素
    adj = F.normalize(adj + I, p=1)
    #normalize函数进行规范化:p:范数公式中的指数值。
    #若p=1，则adj中某行：某个元素的规范化值为该元素值除以该行所有元素值之和；
    #若p=2，则adj中某行：某个元素的规范化之为该元素值除以：根号（该行所有元素平方和）
    adj = to_sparse(adj)
    #将adj中所有非0元素拉出来，形成一个新的adj
    
    return adj


def gen_test_adj_mat_tensor(data, trte_idx, parameter, metric="cosine"):
    assert metric == "cosine", "Only cosine distance implemented"
    adj = torch.zeros((data.shape[0], data.shape[0]))
    if cuda:
        adj = adj.cuda()
    num_tr = len(trte_idx["tr"])
    test_val_idx = trte_idx["te"] + trte_idx["va"]
    
    dist_tr2te = cosine_distance_torch(data[trte_idx["tr"]], data[test_val_idx]) #计算tr和te间的余弦相似度
    g_tr2te = graph_from_dist_tensor(dist_tr2te, parameter, self_dist=False)
    if metric == "cosine":
        adj[:num_tr,num_tr:] = 1-dist_tr2te
    else:
        raise NotImplementedError
    adj[:num_tr,num_tr:] = adj[:num_tr,num_tr:]*g_tr2te
    
    dist_te2tr = cosine_distance_torch(data[test_val_idx], data[trte_idx["tr"]])
    g_te2tr = graph_from_dist_tensor(dist_te2tr, parameter, self_dist=False)
    if metric == "cosine":
        adj[num_tr:,:num_tr] = 1-dist_te2tr
    else:
        raise NotImplementedError
    adj[num_tr:,:num_tr] = adj[num_tr:,:num_tr]*g_te2tr # retain selected edges
    
    adj_T = adj.transpose(0,1)
    I = torch.eye(adj.shape[0])
    if cuda:
        I = I.cuda()
    adj = adj + adj_T*(adj_T > adj).float() - adj*(adj_T > adj).float()
    adj = F.normalize(adj + I, p=1)
    adj = to_sparse(adj)
    
    return adj


def save_model_dict(folder, model_dict,fold_repeat,split_time):
    if not os.path.exists(folder):
        os.makedirs(folder)
    subfolder=os.path.join(folder,str(fold_repeat),str(split_time))
    if not os.path.exists(subfolder):
        os.makedirs(subfolder)
    for module in model_dict:
        torch.save(model_dict[module].state_dict(), os.path.join(subfolder, module+".pth"))
            
    
def load_model_dict(folder, model_dict,fold_repeat,split_time):
    subfolder = os.path.join(folder, str(fold_repeat), str(split_time))
    for module in model_dict:
        if os.path.exists(os.path.join(subfolder, module+".pth")):
#            print("Module {:} loaded!".format(module))
                model_dict[module].load_state_dict(torch.load(os.path.join(subfolder, module+".pth"),map_location=device))#, map_location="cuda:{:}".format(torch.cuda.current_device())))
                model_dict[module]=model_dict[module].eval()
        else:
            print("WARNING: Module {:} from model_dict is not loaded!".format(module))
        if cuda:
            model_dict[module].cuda()    
    return model_dict