import random
from al_mlp.calcs import DeltaCalc
from al_mlp.utils import write_to_db,convert_to_singlepoint, compute_with_calc
import ase
from ase.db import connect

class OfflineActiveLearner:
    """Offline Active Learner

    Parameters
    ----------

    learner_settings: dict
        Dictionary of learner parameters and settings.

    trainer: object
        An isntance of a trainer that has a train and predict method.
 
    trainer_calc: ase Calculator object
         Calculator used for predicting image properties.

    training_data: list
        A list of ase.Atoms objects that have attached calculators.
        Used as the first set of training data.

    parent_calc: ase Calculator object
        Calculator used for querying training data.

    base_calc: ase Calculator object
        Calculator used to calculate delta data for training
  
    ensemble: boolean.
        Whether to train an ensemble of models to make predictions. ensemble
        must be True if uncertainty based query methods are to be used.

    """

    def __init__(
        self, learner_params, trainer,trainer_calc, training_data, parent_calc, base_calc, ensemble = False
    ):
        self.learner_params = learner_params
        self.trainer = trainer
        self.trainer_calc = trainer_calc
        self.training_data = training_data
        self.parent_calc = parent_calc
        self.base_calc = base_calc
        self.ensemble = ensemble
        self.calcs = [parent_calc, base_calc]
        self.iteration = 0
        self.init_training_data()

    def init_training_data(self):
        """
        Prepare the training data by attaching delta values for training.
        """

        raw_data = self.training_data
        sp_raw_data = convert_to_singlepoint(raw_data)
        parent_ref_image = sp_raw_data[0]
        base_ref_image = compute_with_calc([parent_ref_image], self.base_calc)[0]
        self.refs = [parent_ref_image, base_ref_image]
        self.delta_sub_calc = DeltaCalc(self.calcs, "sub", self.refs)
        self.training_data = compute_with_calc(sp_raw_data, self.delta_sub_calc)

    def learn(self, atomistic_method):
        """
        Conduct offline active learning.

        Parameters
        ----------

        atomistic_method: object
            Define relaxation parameters and starting image.
        """
        max_iterations = self.learner_params["max_iterations"]
        samples_to_retrain = self.learner_params["samples_to_retrain"]
        filename = self.learner_params["filename"]
        file_dir = self.learner_params["file_dir"]
        terminate = False

        while not terminate:
            fn_label = f"{file_dir}{filename}_iter_{self.iteration}"
            if self.iteration > 0:
                self.query_data(sample_candidates,samples_to_retrain)

            self.trainer.train(self.training_data)
            trainer_calc = self.trainer_calc(self.trainer)
            trained_calc = DeltaCalc([trainer_calc, self.base_calc], "add", self.refs)

            atomistic_method.run(
                calc=trained_calc, filename=fn_label
            )
            sample_candidates = list(
                atomistic_method.get_trajectory(
                    filename=fn_label
                )
            )

            terminate = self.check_terminate(max_iterations)
            self.iteration += 1

        self.trained_calc = trained_calc

    def query_data(self, sample_candidates,samples_to_retrain):
        """
        Queries data from a list of images. Calculates the properties and adds them to the training data.

        Parameters
        ----------

        sample_candidates: list
            List of ase atoms objects to query from.
        """
        queries_db = ase.db.connect('queried_images.db')        
        queried_images = self.query_func(sample_candidates,samples_to_retrain)
        write_to_db(queries_db, queried_images)
        self.training_data += compute_with_calc(queried_images, self.delta_sub_calc)

    def check_terminate(self,max_iterations):
        """
        Default termination function. Teminates after 10 iterations
        """
        if self.iteration >= max_iterations:
            return True
        return False

    def query_func(self, sample_candidates,samples_to_retrain):
        """
        Default query strategy. Randomly queries 1 data point.
        """
        random.seed()
        queried_images = random.sample(sample_candidates, samples_to_retrain)
        return queried_images
   
