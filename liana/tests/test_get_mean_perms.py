import numpy as np
import pathlib
from scanpy.datasets import pbmc68k_reduced
from pandas import read_csv

from liana.method._get_mean_perms import get_means_perms

test_path = pathlib.Path(__file__).parent

adata = pbmc68k_reduced()
adata.X = adata.raw.X
adata.obs['label'] = adata.obs.bulk_labels

all_defaults = read_csv(test_path.joinpath("data/all_defaults.csv"), index_col=0)

perms, ligand_pos, receptor_pos, labels_pos = \
    get_means_perms(adata=adata, lr_res=all_defaults, n_perms=100, seed=1337)


def test_perms():
    assert perms.shape == (100, 10, 765)

    desired = np.array([45615.15418553, 45737.95729483, 45575.47318892, 45559.41832494,
                        45542.32316456, 45593.50440302, 45591.03955124, 45561.79108855,
                        45698.86540851, 45543.95444739])
    expected = np.sum(np.sum(perms, axis=0), axis=1)

    assert np.testing.assert_almost_equal(desired, expected, decimal=3) is None


def test_positions():
    assert ligand_pos['MIF'] == 740
    assert receptor_pos['CD4'] == 465
    assert labels_pos['Dendritic'] == 9

