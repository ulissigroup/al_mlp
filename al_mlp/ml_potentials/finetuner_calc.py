from ase.calculators.calculator import all_changes
from ase.atoms import Atoms
from al_mlp.ml_potentials.ml_potential_calc import MLPCalc
from torch.utils.data import Dataset
from ocpmodels.preprocessing import AtomsToGraphs
import sys, os


class FinetunerCalc(MLPCalc):
    """
    Open Catalyst Project Finetuner/Transfer learning calculator.
    This class serves as a parent class for calculators that want to instantiate one of the ocp models for finetuning.
    Child classes must implement the init_model function for their given model, keeping unfrozen whichever weights they want finetuned.

    By default simply ticks up a counter to simulate std uncertainty metric
    Ensemble calcs implementing uncertainty should also overwrite train_ocp() and calculate_ml()

    Parameters
    ----------
    ocp_calc: OCPCalculator
        a constructed OCPCalculator object using some pretrained checkpoint file and a model yaml file

    mlp_params: dict
        dictionary of parameters to be passed to be used for initialization of the model/calculator
    """

    implemented_properties = ["energy", "forces", "stds"]

    def __init__(
        self,
        mlp_params: dict = {},
    ):
        MLPCalc.__init__(self, mlp_params=mlp_params)

        self.ml_model = False
        self.max_neighbors = self.mlp_params.get("max_neighbors", 50)
        self.cutoff = self.mlp_params.get("cutoff", 6)
        self.energy_training = self.mlp_params.get("energy_training", False)

    def init_model(self):
        """
        To be overwritten and then called by subclass.
        Initialize a new self.ocp_calc ml model using the stored parameter dictionary
        """
        self.ml_model = True
        self.ocp_calc.trainer.train_dataset = GenericDB()

        self.ocp_calc.trainer.step = 0
        self.ocp_calc.trainer.epoch = 0

    def calculate_ml(self, atoms, properties, system_changes) -> tuple:
        """
        Give ml model the ocp_descriptor to calculate properties : energy, forces, uncertainties.

        Args:
            ocp_descriptor: list object containing the descriptor of the atoms object

        Returns:
            tuple: (energy, forces, energy_uncertainty, force_uncertainties)
        """
        self.ocp_calc.calculate(atoms, properties, system_changes)
        e_mean = self.ocp_calc.results["energy"]
        f_mean = self.ocp_calc.results["forces"]

        self.train_counter += 1
        e_std = f_std = self.train_counter * 0.01

        return e_mean, f_mean, e_std, f_std

    def calculate(self, atoms=None, properties=None, system_changes=all_changes):
        """
        Calculate properties including: energy, forces, uncertainties.

        Args:
            atoms: ase Atoms object
        """
        MLPCalc.calculate(
            self, atoms=atoms, properties=properties, system_changes=system_changes
        )

        energy, forces, energy_uncertainty, force_uncertainties = self.calculate_ml(
            atoms, properties, system_changes
        )

        self.results["energy"] = energy
        self.results["forces"] = forces
        self.results["stds"] = [energy_uncertainty, force_uncertainties]
        self.results["force_stds"] = force_uncertainties
        self.results["energy_stds"] = energy_uncertainty
        atoms.info["energy_stds"] = self.results["energy_stds"]
        atoms.info["max_force_stds"] = self.results["force_stds"]
        # atoms.info["max_force_stds"] = np.nanmax(self.results["force_stds"])
        return

    def train(self, parent_dataset: "list[Atoms]", new_dataset: "list[Atoms]" = None):
        """
        Train the ml model by fitting a new model on the parent dataset,
        or partial fit the current model on just the new_dataset

        Args:
            parent_dataset: list of all the descriptors to be trained on

            new_dataset: list of just the new descriptors to partially fit on
        """
        self.train_counter = 0
        if not self.ml_model or not new_dataset:
            sys.stdout = open(os.devnull, "w")
            self.init_model()
            sys.stdout = sys.__stdout__

            self.train_ocp(parent_dataset)
        else:
            self.train_ocp(new_dataset)

    def train_ocp(self, dataset):
        "overwritable if doing ensembling of ocp calcs"
        train_loader = self.get_data_from_atoms(dataset)
        self.ocp_calc.trainer.train_loader = train_loader
        self.ocp_calc.trainer.train()

    def get_data_from_atoms(self, dataset):
        """
        get train_loader object to replace for the ocp model trainer to train on
        """
        a2g = AtomsToGraphs(
            max_neigh=self.max_neighbors,
            radius=self.cutoff,
            r_energy=True,
            r_forces=True,
            r_distances=True,
            r_edges=True,
        )

        graphs_list = [a2g.convert(atoms) for atoms in dataset]

        for graph in graphs_list:
            graph.fid = 0
            graph.sid = 0

        graphs_list_dataset = GraphsListDataset(graphs_list)

        train_sampler = self.ocp_calc.trainer.get_sampler(
            graphs_list_dataset, 1, shuffle=False
        )
        self.ocp_calc.trainer.train_sampler = train_sampler

        data_loader = self.ocp_calc.trainer.get_dataloader(
            graphs_list_dataset,
            train_sampler,
        )

        return data_loader


class GraphsListDataset(Dataset):
    def __init__(self, graphs_list):
        self.graphs_list = graphs_list

    def __len__(self):
        return len(self.graphs_list)

    def __getitem__(self, idx):
        graph = self.graphs_list[idx]
        return graph


class GenericDB:
    def __init__(self):
        pass

    def close_db(self):
        pass
