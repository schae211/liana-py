import numba as nb
import numpy as np
from scipy.stats import rankdata
from liana.method.sp._spatial_utils import _global_zscore_pvals, _global_permutation_pvals, _local_permutation_pvals, _local_zscore_pvals, _standardize_matrix


@nb.njit(nb.float32(nb.float32[:], nb.float32[:], nb.float32[:], nb.float32, nb.boolean), cache=True)
def _wcorr(x, y, w, wsum, rank):
    
    if rank:
        x = np.argsort(x).argsort().astype(nb.float32)
        y = np.argsort(y).argsort().astype(nb.float32)
    
    wx = w * x
    wy = w * y
    
    numerator = wsum * sum(wx * y) - sum(wx) * sum(wy)
    
    denominator_x = wsum * sum(w * (x**2)) - sum(wx)**2
    denominator_y = wsum * sum(w * (y**2)) - sum(wy)**2
    denominator = (denominator_x * denominator_y)
    
    if (denominator == 0) or (numerator == 0):
        return 0
    
    return numerator / (denominator**0.5)


@nb.njit(nb.float32(nb.float32[:], nb.float32[:], nb.float32[:], nb.float32, nb.int8), cache=True)
def _wcoex(x, y, w, wsum, method):
        if method == 0: # pearson
            c = _wcorr(x, y, w, wsum, False)
        elif method == 1: # spearman
            c = _wcorr(x, y, w, wsum, True)
            ## Any other method
        else: 
            raise ValueError("method not supported")
        return c



# 0 = pearson, 1 = spearman 
@nb.njit(nb.float32[:,:](nb.float32[:,:], nb.float32[:,:], nb.float32[:,:], nb.float32, nb.int8), parallel=True, cache=True)
def _masked_coexpressions(x_mat, y_mat, weight, weight_thr, method):
    spot_n = x_mat.shape[0]
    xy_n = x_mat.shape[1]
    
    local_corrs = np.zeros((spot_n, xy_n), dtype=nb.float32)
    
    for i in nb.prange(spot_n):
        w = weight[i, :]
        msk = w > weight_thr
        wsum = sum(w[msk])
        
        for j in range(xy_n):
            x = x_mat[:, j][msk]
            y = y_mat[:, j][msk]
            
            local_corrs[i, j] = _wcoex(x, y, w[msk], wsum, method)
    
    # fix numpy/numba sum imprecision, https://github.com/numba/numba/issues/8749
    local_corrs = np.clip(a=local_corrs, a_min=-1.0, a_max=1.0, out=local_corrs)
    
    return local_corrs


@nb.njit(nb.float32[:,:](nb.float32[:,:], nb.float32[:,:], nb.float32[:,:], nb.float32), cache=True)
def _masked_pearson(x_mat, y_mat, weight, weight_thr):
    return _masked_coexpressions(x_mat, y_mat, weight, weight_thr, method=0) 


@nb.njit(nb.float32[:,:](nb.float32[:,:], nb.float32[:,:], nb.float32[:,:], nb.float32), cache=True)
def _masked_spearman(x_mat, y_mat, weight, weight_thr):
    return _masked_coexpressions(x_mat, y_mat, weight, weight_thr, method=1)


def _vectorized_correlations(x_mat, y_mat, weight, method="pearson"):
    """
    Vectorized implementation of weighted correlations.
    
    Note: due to the imprecision of np.sum and np.dot, the function is accurate to 5 decimal places.
    
    """
    if method not in ["pearson", "spearman"]:
        raise ValueError("method must be one of 'pearson', 'spearman'")
    
    # transpose
    x_mat, y_mat = x_mat.T, y_mat.T
    

    weight_sums = np.sum(weight, axis = 0).flatten()
        
    if method=="spearman":
        x_mat = rankdata(x_mat, axis=1)
        y_mat = rankdata(y_mat, axis=1)
    
    # standard pearson
    n1 = (((x_mat * y_mat).dot(weight)) * weight_sums)
    n2 = (x_mat.dot(weight)) * (y_mat.dot(weight))
    numerator = n1 - n2
    
    denominator_x = (weight_sums * (x_mat ** 2).dot(weight)) - (x_mat.dot(weight))**2
    denominator_y = (weight_sums * (y_mat ** 2).dot(weight)) - (y_mat.dot(weight))**2
    denominator = (denominator_x * denominator_y)
    
    # numpy sum is unstable below 1e-6... 
    # results in the denominator being smaller than the numerator
    denominator[denominator < 1e-6] = 0
    denominator = denominator ** 0.5
    
    zeros = np.zeros(numerator.shape)
    local_corrs = np.divide(numerator, denominator, out=zeros, where=denominator!=0)
    
    # fix numpy/numba sum imprecision, https://github.com/numba/numba/issues/8749
    local_corrs = np.clip(local_corrs, -1, 1, out=local_corrs, dtype=np.float32)
    
    return local_corrs


def _vectorized_pearson(x_mat, y_mat, weight):
    return _vectorized_correlations(x_mat, y_mat, weight, method="pearson")


def _vectorized_spearman(x_mat, y_mat, weight):
    return _vectorized_correlations(x_mat, y_mat, weight, method="spearman")


def _vectorized_cosine(x_mat, y_mat, weight):
    x_mat, y_mat = x_mat.T, y_mat.T    
    
    xy_dot = (x_mat * y_mat).dot(weight)
    x_dot = (x_mat ** 2).dot(weight.T)
    y_dot = (y_mat ** 2).dot(weight.T)
    denominator = (x_dot * y_dot) + np.finfo(np.float32).eps
    
    return xy_dot / (denominator**0.5)


def _vectorized_jaccard(x_mat, y_mat, weight):
    # binarize
    x_mat, y_mat = x_mat > 0, y_mat > 0 ## TODO, only positive?
    # transpose
    x_mat, y_mat = x_mat.T, y_mat.T    
    
    # intersect and union
    numerator = np.dot(np.minimum(x_mat, y_mat), weight)
    denominator = np.dot(np.maximum(x_mat, y_mat), weight) + np.finfo(np.float32).eps
    
    return numerator / denominator


def _local_morans(x_mat, y_mat, weight):
    """

    Parameters
    ----------
    x_mat
        2D array with x variables
    y_mat
        2D array with y variables
    
    Returns
    -------
    Returns 2D array of local Moran's I with shape(n_spot, xy_n)

    """
    
    local_x = x_mat * (weight @ y_mat)
    local_y = x_mat * (weight @ y_mat)
    local_r = (local_x + local_y).T

    return local_r


def _handle_functions(function_name): # TODO improve this, maybe use a dict, or a class
    function_name = function_name.lower()
    
    if function_name == "pearson":
        return _vectorized_pearson
    elif function_name == "spearman":
        return _vectorized_spearman
    elif function_name == "masked_pearson":
        return _masked_pearson
    elif function_name == "masked_spearman":
        return _masked_spearman
    elif function_name == "cosine":
        return _vectorized_cosine
    elif function_name == "jaccard":
        return _vectorized_jaccard
    elif function_name == "morans":
        return _local_morans
    else:
        raise ValueError("Function not implemented")
