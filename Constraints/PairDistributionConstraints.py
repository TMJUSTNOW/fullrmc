"""
PairDistributionConstraints contains classes for all constraints related
to experimental pair distribution functions.

.. inheritance-diagram:: fullrmc.Constraints.PairDistributionConstraints
    :parts: 1
"""

# standard libraries imports
import itertools
import copy

# external libraries imports
import numpy as np
from pdbParser.Utilities.Database import is_element_property, get_element_property
from pdbParser.Utilities.Collection import get_normalized_weighting

# fullrmc imports
from fullrmc.Globals import INT_TYPE, FLOAT_TYPE, PI, PRECISION, LOGGER
from fullrmc.Core.Collection import is_number, is_integer, get_path, reset_if_collected_out_of_date, get_real_elements_weight
from fullrmc.Core.Constraint import Constraint, ExperimentalConstraint
from fullrmc.Core.pairs_histograms import multiple_pairs_histograms_coords, full_pairs_histograms_coords
from fullrmc.Constraints.Collection import ShapeFunction


class PairDistributionConstraint(ExperimentalConstraint):
    """
    Controls the total reduced pair distribution function (pdf) of atomic
    configuration noted as G(r). The pair distribution function is directly
    calculated from powder diffraction experimental data. It is obtained
    from the experimentally determined total-scattering structure
    function S(Q), by a Sine Fourier transform according to.

    .. math::

        G(r) = \\frac{2}{\\pi} \\int_{0}^{\\infty} Q [S(Q)-1]sin(Qr)dQ \n
        S(Q) = 1+ \\frac{1}{Q} \\int_{0}^{\\infty} G(r) sin(Qr) dr

    Theoretically G(r) oscillates about zero. Also :math:`G(r) \\rightarrow 0`
    when :math:`r \\rightarrow \\infty` and :math:`G(r) \\rightarrow 0` when
    :math:`r \\rightarrow 0` with a slope of :math:`-4\\pi\\rho_{0}`
    where :math:`\\rho_{0}` is the number density of the material. \n
    Model wise, G(r) is computed after calculating the so called Pair
    Correlation Function noted as g(r). The relation between G(r) and g(r)
    is given by\n

    .. math::

        G(r) = 4 \\pi r (\\rho_{r} - \\rho_{0})
             = 4 \\pi \\rho_{0} r (g(r)-1)
             = \\frac{R(r)}{r} - 4 \\pi r \\rho_{0}

    :math:`\\rho_{r}` is the number density fluctuation at distance :math:`r`.
    The computation of g(r) is straightforward from an atomistic model and it
    is given by :math:`g(r)=\\rho_{r} / \\rho_{0}`.\n

    The radial distribution function noted :math:`R(r)` is a very important
    function because it describes directly the system's structure.
    :math:`R(r)dr` gives the number of atoms in an annulus of thickness
    dr at distance r from another atom. Therefore, the coordination number,
    or the number of neighbors within the distances interval :math:`[a,b]`
    is given by :math:`\\int_{a}^{b} R(r) dr`\n

    Finally, g(r) is calculated after binning all pair atomic distances into
    a weighted histograms of values :math:`n(r)` from which local number
    densities are computed as the following:

    .. math::
        g(r) = \\sum \\limits_{i,j}^{N} w_{i,j} \\frac{\\rho_{i,j}(r)}{\\rho_{0}}
             = \\sum \\limits_{i,j}^{N} w_{i,j} \\frac{n_{i,j}(r) / v(r)}{N_{i,j} / V}

    Where:\n
    :math:`Q` is the momentum transfer. \n
    :math:`r` is the distance between two atoms. \n
    :math:`\\rho_{i,j}(r)` is the pair density function of atoms i and j. \n
    :math:`\\rho_{0}` is the  average number density of the system. \n
    :math:`w_{i,j}` is the relative weighting of atom types i and j. \n
    :math:`R(r)` is the radial distribution function (rdf). \n
    :math:`N` is the total number of atoms. \n
    :math:`V` is the volume of the system. \n
    :math:`n_{i,j}(r)` is the number of atoms i neighbouring j at a distance r. \n
    :math:`v(r)` is the annulus volume at distance r and of thickness dr. \n
    :math:`N_{i,j}` is the total number of atoms i and j in the system. \n

    :Parameters:
        #. experimentalData (numpy.ndarray, string): Experimental data as
           numpy.ndarray or string path to load data using numpy.loadtxt.
        #. dataWeights (None, numpy.ndarray): Weights array of the same number
           of points of experimentalData used in the constraint's standard
           error computation. Therefore particular fitting emphasis can be
           put on different data points that might be considered as more or less
           important in order to get a reasonable and plausible modal.\n
           If None is given, all data points are considered of the same
           importance in the computation of the constraint's standard error.\n
           If numpy.ndarray is given, all weights must be positive and all
           zeros weighted data points won't contribute to the total
           constraint's standard error. At least a single weight point is
           required to be non-zeros and the weights array will be automatically
           scaled upon setting such as the the sum of all the weights
           is equal to the number of data points.
        #. weighting (string): The elements weighting scheme. It must be any
           atomic attribute (atomicNumber, neutronCohb, neutronIncohb,
           neutronCohXs, neutronIncohXs, atomicWeight, covalentRadius) defined
           in pdbParser database. In case of xrays or neutrons experimental
           weights, one can simply set weighting to 'xrays' or 'neutrons'
           and the value will be automatically adjusted to respectively
           'atomicNumber' and 'neutronCohb'. If attribute values are
           missing in the pdbParser database, atomic weights must be
           given in atomsWeight dictionary argument.
        #. atomsWeight (None, dict): Atoms weight dictionary where keys are
           atoms element and values are custom weights. If None is given
           or partially given, missing elements weighting will be fully set
           given weighting scheme.
        #. scaleFactor (number): A normalization scale factor used to normalize
           the computed data to the experimental ones.
        #. adjustScaleFactor (list, tuple): Used to adjust fit or guess
           the best scale factor during stochastic engine runtime.
           It must be a list of exactly three entries.\n
           #. The frequency in number of generated moves of finding the best
              scale factor. If 0 frequency is given, it means that the scale
              factor is fixed.
           #. The minimum allowed scale factor value.
           #. The maximum allowed scale factor value.
        #. shapeFuncParams (None, numpy.ndarray, dict): The shape function is
           subtracted from the total G(r). It must be used when non-periodic
           boundary conditions are used to take into account the atomic
           density drop and to correct for the :math:`\\rho_{0}` approximation.
           The shape function can be set to None which means unsused, or set
           as a constant shape given by a numpy.ndarray or computed
           from all atoms and updated every 'updateFreq' accepted moves.
           If dict is given the following keywords can be given, otherwise
           default values will be automatically set.\n
           * **rmin (number) default (0.00) :** The minimum distance in
             :math:`\\AA` considered upon building the histogram prior to
             computing the shape function. If not defined, rmin will be
             set automatically to 0.
           * **rmax (None, number) default (None) :** The maximum distance
             in :math:`\\AA` considered upon building the histogram prior
             to computing the shape function. If not defnined, rmax will
             be automatically set to :math:`maximum\ box\ length + 10\\AA`
             at engine runtime.
           * **dr (number) default (0.5) :** The bin size in :math:`\\AA`
             considered upon building the histogram prior to computing the
             shape function. If not defined, it will be automatically set
             to 0.5.
           * **qmin (number) default (0.001) :** The minimum reciprocal
             distance q in :math:`\\AA^{-1}` considered to compute the
             shape function. If not defined, it will be automatically
             set to 0.001.
           * **qmax (number) default (0.75) :** The maximum reciprocal
             distance q in :math:`\\AA^{-1}` considered to compute the
             shape function. If not defined, it will be automatically
             set to 0.75.
           * **dq (number) default (0.005) :** The reciprocal distance bin
             size in :math:`\\AA^{-1}` considered to compute the shape
             function. If not defined, it will be automatically
             set to 0.005.
           * **updateFreq (integer) default (1000) :** The frequency of
             recomputing the shape function in number of accpeted moves.
        #. windowFunction (None, numpy.ndarray): The window function to
           convolute with the computed pair distribution function of the
           system prior to comparing it with the experimental data. In
           general, the experimental pair distribution function G(r) shows
           artificial wrinkles, among others the main reason is because
           G(r) is computed by applying a sine Fourier transform to the
           experimental structure factor S(q). Therefore window function is
           used to best imitate the numerical artefacts in the experimental
           data.
        #. limits (None, tuple, list): The distance limits to compute the
           histograms. If None is given, the limits will be automatically
           set the the min and max distance of the experimental data.
           Otherwise, a tuple of exactly two items where the first is the
           minimum distance or None and the second is the maximum distance
           or None.

    **NB**: If adjustScaleFactor first item (frequency) is 0, the scale factor
    will remain untouched and the limits minimum and maximum won't be checked.

    .. code-block:: python

        # import fullrmc modules
        from fullrmc.Engine import Engine
        from fullrmc.Constraints.PairDistributionConstraints import PairDistributionConstraint

        # create engine
        ENGINE = Engine(path='my_engine.rmc')

        # set pdb file
        ENGINE.set_pdb('system.pdb')

        # create and add constraint
        PDC = PairDistributionConstraint(experimentalData="pdf.dat", weighting="atomicNumber")
        ENGINE.add_constraints(PDC)

    """
    def __init__(self, experimentalData, dataWeights=None, weighting="atomicNumber",
                       atomsWeight=None, scaleFactor=1.0, adjustScaleFactor=(0, 0.8, 1.2),
                       shapeFuncParams=None, windowFunction=None, limits=None):
        self.__limits = limits
        # initialize constraint
        super(PairDistributionConstraint, self).__init__(experimentalData=experimentalData, dataWeights=dataWeights, scaleFactor=scaleFactor, adjustScaleFactor=adjustScaleFactor)
        # set elements weighting
        self.set_weighting(weighting)
        # set atomsWeight
        self.set_atoms_weight(atomsWeight)
        # set window function
        self.set_window_function(windowFunction)
        # set shape function parameters
        self.set_shape_function_parameters(shapeFuncParams)

        # set frame data
        FRAME_DATA = [d for d in self.FRAME_DATA]
        FRAME_DATA.extend(['_PairDistributionConstraint__bin',
                           '_PairDistributionConstraint__minDistIdx',
                           '_PairDistributionConstraint__maxDistIdx',
                           '_PairDistributionConstraint__minimumDistance',
                           '_PairDistributionConstraint__maximumDistance',
                           '_PairDistributionConstraint__shellCenters',
                           '_PairDistributionConstraint__edges',
                           '_PairDistributionConstraint__histogramSize',
                           '_PairDistributionConstraint__experimentalDistances',
                           '_PairDistributionConstraint__experimentalPDF',
                           '_PairDistributionConstraint__shellVolumes',
                           '_PairDistributionConstraint__elementsPairs',
                           '_PairDistributionConstraint__weighting',
                           '_PairDistributionConstraint__atomsWeight',
                           '_PairDistributionConstraint__weightingScheme',
                           '_PairDistributionConstraint__windowFunction',
                           '_PairDistributionConstraint__limits',
                           '_elementsWeight',
                           '_usedDataWeights',
                           '_shapeFuncParams',
                           '_shapeUpdateFreq',
                           '_shapeArray', ] )

        RUNTIME_DATA = [d for d in self.RUNTIME_DATA]
        RUNTIME_DATA.extend( ['_shapeArray'] )
        object.__setattr__(self, 'FRAME_DATA',   tuple(FRAME_DATA)  )
        object.__setattr__(self, 'RUNTIME_DATA', tuple(RUNTIME_DATA) )

    def __set_used_data_weights(self, minDistIdx=None, maxDistIdx=None):
        # set used dataWeights
        if self.dataWeights is None:
            self._usedDataWeights = None
        else:
            if minDistIdx is None:
                minDistIdx = 0
            if maxDistIdx is None:
                maxDistIdx = self.experimentalData.shape[0]
            self._usedDataWeights  = np.copy(self.dataWeights[minDistIdx:maxDistIdx+1])
            assert np.sum(self._usedDataWeights), LOGGER.error("used points dataWeights are all zero.")
            self._usedDataWeights /= FLOAT_TYPE( np.sum(self._usedDataWeights) )
            self._usedDataWeights *= FLOAT_TYPE( len(self._usedDataWeights) )
        # dump to repository
        self._dump_to_repository({'_usedDataWeights': self._usedDataWeights})

    def _on_collector_reset(self):
        pass

    def _update_shape_array(self):
        rmin = self._shapeFuncParams['rmin']
        rmax = self._shapeFuncParams['rmax']
        dr   = self._shapeFuncParams['dr'  ]
        qmin = self._shapeFuncParams['qmin']
        qmax = self._shapeFuncParams['qmax']
        dq   = self._shapeFuncParams['dq'  ]
        if rmax is None:
            if self.engine.isPBC:
                a = self.engine.boundaryConditions.get_a()
                b = self.engine.boundaryConditions.get_b()
                c = self.engine.boundaryConditions.get_c()
                rmax = FLOAT_TYPE( np.max([a,b,c]) + 10 )
            else:
                coordsCenter = np.sum(self.engine.realCoordinates, axis=0)/self.engine.realCoordinates.shape[0]
                coordinates  = self.engine.realCoordinates-coordsCenter
                distances    = np.sqrt( np.sum(coordinates**2, axis=1) )
                maxDistance  = 2.*np.max(distances)
                rmax = FLOAT_TYPE( maxDistance + 10 )
                LOGGER.warn("Better set shape function rmax with infinite boundary conditions. Here value is automatically set to %s"%rmax)
        shapeFunc  = ShapeFunction(engine    = self.engine,
                                   weighting = self.__weighting,
                                   qmin=qmin, qmax=qmax, dq=dq,
                                   rmin=rmin, rmax=rmax, dr=dr)
        self._shapeArray = shapeFunc.get_Gr_shape_function( self.shellCenters )
        del shapeFunc
        # dump to repository
        self._dump_to_repository({'_shapeArray': self._shapeArray})

    def _reset_standard_error(self):
        # recompute squared deviation
        if self.data is not None:
            totalPDF = self.__get_total_Gr(self.data, rho0=self.engine.numberDensity)
            self.set_standard_error(self.compute_standard_error(modelData = totalPDF))

    def _runtime_initialize(self):
        if self._shapeFuncParams is None:
            self._shapeArray = None
        elif isinstance(self._shapeFuncParams, np.ndarray):
            self._shapeArray = self._shapeFuncParams[self.__minDistIdx:self.__maxDistIdx+1]
        elif isinstance(self._shapeFuncParams, dict) and self._shapeArray is None:
            self._update_shape_array()
        # reset standard error
        self._reset_standard_error()
        # set last shape update flag
        self._lastShapeUpdate = self.engine.accepted

    def _runtime_on_step(self):
        """ Update shape function when needed. and update engine total """
        if self._shapeUpdateFreq and self._shapeFuncParams is not None:
            if (self._lastShapeUpdate != self.engine.accepted) and not (self.engine.accepted%self._shapeUpdateFreq):
                # reset shape array
                self._update_shape_array()
                # reset standard error
                self._reset_standard_error()
                # update engine chiSquare
                oldTotalStandardError = self.engine.totalStandardError
                self.engine.set_total_standard_error()
                LOGGER.info("Constraint '%s' shape function updated, engine chiSquare updated from %.6f to %.6f" %(self.__class__.__name__, oldTotalStandardError, self.engine.totalStandardError))
                self._lastShapeUpdate = self.engine.accepted

    @property
    def bin(self):
        """ Experimental data distances bin."""
        return self.__bin

    @property
    def minimumDistance(self):
        """ Experimental data minimum distances."""
        return self.__minimumDistance

    @property
    def maximumDistance(self):
        """ Experimental data maximum distances."""
        return self.__maximumDistance

    @property
    def histogramSize(self):
        """ Histogram size."""
        return self.__histogramSize

    @property
    def experimentalDistances(self):
        """ Experimental distances array."""
        return self.__experimentalDistances

    @property
    def shellCenters(self):
        """ Shells center array."""
        return self.__shellCenters

    @property
    def shellVolumes(self):
        """ Shells volume array."""
        return self.__shellVolumes

    @property
    def experimentalPDF(self):
        """ Experimental pair distribution function data."""
        return self.__experimentalPDF

    @property
    def elementsPairs(self):
        """ Elements pairs."""
        return self.__elementsPairs

    @property
    def weighting(self):
        """ Elements weighting definition."""
        return self.__weighting

    @property
    def atomsWeight(self):
        """Custom atoms weight"""
        return self.__atomsWeight

    @property
    def weightingScheme(self):
        """ Elements weighting scheme."""
        return self.__weightingScheme

    @property
    def windowFunction(self):
        """ Window function."""
        return self.__windowFunction

    @property
    def limits(self):
        """ Histogram computation limits."""
        return self.__limits

    @property
    def shapeArray(self):
        """ Shape function data array."""
        return self._shapeArray

    @property
    def shapeUpdateFreq(self):
        """Shape function update frequency."""
        return self._shapeUpdateFreq

    def _set_weighting_scheme(self, weightingScheme):
        """To be only used internally by PairCorrelationConstraint"""
        self.__weightingScheme = weightingScheme

    def listen(self, message, argument=None):
        """
        Listens to any message sent from the Broadcaster.

        :Parameters:
            #. message (object): Any python object to send to constraint's
               listen method.
            #. argument (object): Any type of argument to pass to the listeners.
        """
        if message in("engine set", "update molecules indexes"):
            if self.engine is not None:
                self.__elementsPairs   = sorted(itertools.combinations_with_replacement(self.engine.elements,2))
                #self._elementsWeight  = dict([(el,float(get_element_property(el,self.__weighting))) for el in self.engine.elements])
                #self._elementsWeight  = dict([(el,self.__atomsWeight.get(el, float(get_element_property(el,self.__weighting)))) for el in self.engine.elements])
                self._elementsWeight    = get_real_elements_weight(elements=self.engine.elements, weightsDict=self.__atomsWeight, weighting=self.__weighting)
                self.__weightingScheme = get_normalized_weighting(numbers=self.engine.numberOfAtomsPerElement, weights=self._elementsWeight)
                for k, v in self.__weightingScheme.items():
                    self.__weightingScheme[k] = FLOAT_TYPE(v)


            else:
                self.__elementsPairs   = None
                self._elementsWeight  = None
                self.__weightingScheme = None
            # dump to repository
            self._dump_to_repository({'_PairDistributionConstraint__elementsPairs'  : self.__elementsPairs,
                                      '_PairDistributionConstraint__weightingScheme': self.__weightingScheme})
            self.reset_constraint() # ADDED 2017-JAN-08
        elif message in("update boundary conditions",):
            self.reset_constraint()

    def set_shape_function_parameters(self, shapeFuncParams):
        """
        Set the shape function. The shape function can be set to None which
        means unsused, or set as a constant shape given by a numpy.ndarray or
        computed from all atoms and updated every 'updateFreq' accepted moves.
        The shape function is subtracted from the total G(r). It must be used
        when non-periodic boundary conditions are used to take into account
        the atomic density drop and to correct for the :math:`\\rho_{0}`
        approximation.

        :Parameters:
            #. shapeFuncParams (None, numpy.ndarray, dict): The shape function
               is  subtracted from the total G(r). It must be used when
               non-periodic boundary conditions are used to take into account
               the atomic density drop and to correct for the :math:`\\rho_{0}`
               approximation. The shape function can be set to None which means
               unsused, or set as a constant shape given by a numpy.ndarray or
               computed from all atoms and updated every 'updateFreq' accepted
               moves. If dict is given the following keywords can be given,
               otherwise default values will be automatically set.\n
               * **rmin (number) default (0.00) :** The minimum distance in
                 :math:`\\AA` considered upon building the histogram prior to
                 computing the shape function. If not defined, rmin will be
                 set automatically to 0.
               * **rmax (None, number) default (None) :** The maximum distance
                 in :math:`\\AA` considered upon building the histogram prior
                 to computing the shape function. If not defnined, rmax will
                 be automatically set to :math:`maximum\ box\ length + 10\\AA`
                 at engine runtime.
               * **dr (number) default (0.5) :** The bin size in :math:`\\AA`
                 considered upon building the histogram prior to computing the
                 shape function. If not defined, it will be automatically set
                 to 0.5.
               * **qmin (number) default (0.001) :** The minimum reciprocal
                 distance q in :math:`\\AA^{-1}` considered to compute the
                 shape function. If not defined, it will be automatically
                 set to 0.001.
               * **qmax (number) default (0.75) :** The maximum reciprocal
                 distance q in :math:`\\AA^{-1}` considered to compute the
                 shape function. If not defined, it will be automatically
                 set to 0.75.
               * **dq (number) default (0.005) :** The reciprocal distance bin
                 size in :math:`\\AA^{-1}` considered to compute the shape
                 function. If not defined, it will be automatically
                 set to 0.005.
               * **updateFreq (integer) default (1000) :** The frequency of
                 recomputing the shape function in number of accpeted moves.

        """
        self._shapeArray = None
        if shapeFuncParams is None:
            self._shapeFuncParams = None
            self._shapeUpdateFreq = 0
        elif isinstance(shapeFuncParams, dict):
            rmin            = FLOAT_TYPE( shapeFuncParams.get('rmin',0.00 ) )
            rmax            =             shapeFuncParams.get('rmax',None )
            dr              = FLOAT_TYPE( shapeFuncParams.get('dr'  ,0.5  ) )
            qmin            = FLOAT_TYPE( shapeFuncParams.get('qmin',0.001) )
            qmax            = FLOAT_TYPE( shapeFuncParams.get('qmax',0.75 ) )
            dq              = FLOAT_TYPE( shapeFuncParams.get('dq'  ,0.005) )
            self._shapeFuncParams = {'rmin':rmin, 'rmax':rmax, 'dr':dr,
                                      'qmin':qmin, 'qmax':qmax, 'dq':dq }
            self._shapeUpdateFreq = INT_TYPE( shapeFuncParams.get('updateFreq',1000) )
        else:
            assert isinstance(shapeFuncParams, (list,tuple,np.ndarray)), LOGGER.error("shapeFuncParams must be None, numpy.ndarray or a dictionary")
            try:
                shapeArray = np.array(shapeFuncParams)
            except:
                raise LOGGER.error("constant shapeFuncParams must be numpy.ndarray castable")
            assert len(shapeFuncParams.shape) == 1, LOGGER.error("numpy.ndarray shapeFuncParams must be of dimension 1")
            assert shapeFuncParams.shape[0] == self.experimentalData.shape[0], LOGGER.error("numpy.ndarray shapeFuncParams must have the same experimental data length")
            for n in shapeFuncParams:
                assert is_number(n), LOGGER.error("numpy.ndarray shapeFuncParams must be numbers")
            self._shapeFuncParams = shapeFuncParams.astype(FLOAT_TYPE)
            self._shapeUpdateFreq = 0
        # dump to repository
        self._dump_to_repository({'_shapeFuncParams': self._shapeFuncParams,
                                  '_shapeUpdateFreq': self._shapeUpdateFreq})

    def set_weighting(self, weighting):
        """
        Set elements weighting. It must be a valid entry of pdbParser atom's
        database.

        :Parameters:
            #. weighting (string): The elements weighting scheme. It must be
               any atomic attribute (atomicNumber, neutronCohb, neutronIncohb,
               neutronCohXs, neutronIncohXs, atomicWeight, covalentRadius)
               defined in pdbParser database. In case of xrays or neutrons
               experimental weights, one can simply set weighting to 'xrays'
               or 'neutrons' and the value will be automatically adjusted to
               respectively 'atomicNumber' and 'neutronCohb'. If attribute
               values are missing in the pdbParser database, atomic weights
               must be given in atomsWeight dictionary argument.
        """
        if weighting.lower() in ["xrays","x-rays","xray","x-ray"]:
            LOGGER.fixed("'%s' weighting is set to atomicNumber")
            weighting = "atomicNumber"
        elif weighting.lower() in ["neutron","neutrons"]:
            LOGGER.fixed("'%s' weighting is set to neutronCohb")
            weighting = "neutronCohb"
        assert is_element_property(weighting),LOGGER.error( "weighting is not a valid pdbParser atoms database entry")
        assert weighting != "atomicFormFactor", LOGGER.error("atomicFormFactor weighting is not allowed")
        self.__weighting = weighting
        # dump to repository
        self._dump_to_repository({'_PairDistributionConstraint__weighting': self.__weighting})

    def set_atoms_weight(self, atomsWeight):
        """
        Custom set atoms weight. This is the way to setting a atoms weights
        different than the given weighting scheme.

        :Parameters:
            #. atomsWeight (None, dict): Atoms weight dictionary where keys are
               atoms element and values are custom weights. If None is given
               or partially given, missing elements weighting will be fully set
               given weighting scheme.
        """
        if atomsWeight is None:
            AW = {}
        else:
            assert isinstance(atomsWeight, dict),LOGGER.error("atomsWeight must be None or a dictionary")
            AW = {}
            for k, v in atomsWeight.items():
                assert isinstance(k, basestring),LOGGER.error("atomsWeight keys must be strings")
                try:
                    val = FLOAT_TYPE(v)
                except:
                    raise LOGGER.error( "atomsWeight values must be numerical")
                AW[k]=val
        # set atomsWeight
        self.__atomsWeight = AW
        # dump to repository
        self._dump_to_repository({'_PairDistributionConstraint__atomsWeight': self.__atomsWeight})

    def set_window_function(self, windowFunction):
        """
        Set convolution window function.

        :Parameters:
             #. windowFunction (None, numpy.ndarray): The window function to
                convolute with the computed pair distribution function of the
                system prior to comparing it with the experimental data. In
                general, the experimental pair distribution function G(r) shows
                artificial wrinkles, among others the main reason is because
                G(r) is computed by applying a sine Fourier transform to the
                experimental structure factor S(q). Therefore window function is
                used to best imitate the numerical artefacts in the experimental
                data.
        """
        if windowFunction is not None:
            assert isinstance(windowFunction, np.ndarray), LOGGER.error("windowFunction must be a numpy.ndarray")
            assert windowFunction.dtype.type is FLOAT_TYPE, LOGGER.error("windowFunction type must be %s"%FLOAT_TYPE)
            assert len(windowFunction.shape) == 1, LOGGER.error("windowFunction must be of dimension 1")
            assert len(windowFunction) <= self.experimentalData.shape[0], LOGGER.error("windowFunction length must be smaller than experimental data")
            # normalize window function
            windowFunction /= np.sum(windowFunction)
        # check window size
        # set windowFunction
        self.__windowFunction = windowFunction
        # dump to repository
        self._dump_to_repository({'_PairDistributionConstraint__windowFunction': self.__windowFunction})

    def set_experimental_data(self, experimentalData):
        """
        Set constraint's experimental data.

        :Parameters:
            #. experimentalData (numpy.ndarray, string): The experimental
               data as numpy.ndarray or string path to load data using
               numpy.loadtxt function.
        """
        # get experimental data
        super(PairDistributionConstraint, self).set_experimental_data(experimentalData=experimentalData)
        self.__bin = FLOAT_TYPE(self.experimentalData[1,0] - self.experimentalData[0,0])
        # dump to repository
        self._dump_to_repository({'_PairDistributionConstraint__bin': self.__bin})
        # set limits
        self.set_limits(self.__limits)

    def set_data_weights(self, dataWeights):
        """
        Set experimental data points weight.

        :Parameters:
            #. dataWeights (None, numpy.ndarray): Weights array of the same
               number of points of experimentalData used in the constraint's
               standard error computation. Therefore particular fitting
               emphasis can be put on different data points that might be
               considered as more or less important in order to get a
               reasonable and plausible modal.\n
               If None is given, all data points are considered of the same
               importance in the computation of the constraint's standard
               error.\n
               If numpy.ndarray is given, all weights must be positive and all
               zeros weighted data points won't contribute to the total
               constraint's standard error. At least a single weight point is
               required to be non-zeros and the weights array will be
               automatically scaled upon setting such as the the sum of all
               the weights is equal to the number of data points.
        """
        super(PairDistributionConstraint, self).set_data_weights(dataWeights=dataWeights)
        self.__set_used_data_weights()

    def compute_and_set_standard_error(self):
        """ Compute and set constraint's standardError."""
        # set standardError
        totalPDF = self.get_constraint_value()["pdf_total"]
        self.set_standard_error(self.compute_standard_error(modelData = totalPDF))

    def set_limits(self, limits):
        """
        Set the histogram computation limits.

        :Parameters:
            #. limits (None, tuple, list): Distance limits to bound
               experimental data and compute histograms.
               If None is given, the limits will be automatically
               set the the min and max distance of the experimental data.
               Otherwise, a tuple of exactly two items where the first is the
               minimum distance or None and the second is the maximum distance
               or None.
        """
        if limits is None:
            self.__limits = (None, None)
        else:
            assert isinstance(limits, (list, tuple)), LOGGER.error("limits must be None or a list")
            limits = list(limits)
            assert len(limits) == 2, LOGGER.error("limits list must have exactly two elements")
            if limits[0] is not None:
                assert is_number(limits[0]), LOGGER.error("if not None, the first limits element must be a number")
                limits[0] = FLOAT_TYPE(limits[0])
                assert limits[0]>=0, LOGGER.error("if not None, the first limits element must be bigger or equal to 0")
            if limits[1] is not None:
                assert is_number(limits[1]), LOGGER.error("if not None, the second limits element must be a number")
                limits[1] = FLOAT_TYPE(limits[1])
                assert limits[1]>0, LOGGER.error("if not None, the second limits element must be a positive number")
            if  limits[0] is not None and limits[1] is not None:
                assert limits[0]<limits[1], LOGGER.error("if not None, the first limits element must be smaller than the second limits element")
            self.__limits = (limits[0], limits[1])
        # get minimumDistance and maximumDistance indexes
        if self.__limits[0] is None:
            self.__minDistIdx = 0
        else:
            self.__minDistIdx = (np.abs(self.experimentalData[:,0]-self.__limits[0])).argmin()
        if self.__limits[1] is None:
            self.__maxDistIdx = self.experimentalData.shape[0]-1
        else:
            self.__maxDistIdx =(np.abs(self.experimentalData[:,0]-self.__limits[1])).argmin()
        # set minimumDistance, maximumDistance
        self.__minimumDistance = FLOAT_TYPE(self.experimentalData[self.__minDistIdx,0] - self.__bin/2. )
        self.__maximumDistance = FLOAT_TYPE(self.experimentalData[self.__maxDistIdx ,0] + self.__bin/2. )
        self.__shellCenters    = np.array([self.experimentalData[idx,0] for idx in range(self.__minDistIdx,self.__maxDistIdx +1)],dtype=FLOAT_TYPE)
        # set histogram edges
        edges = [self.experimentalData[idx,0] - self.__bin/2. for idx in range(self.__minDistIdx,self.__maxDistIdx +1)]
        edges.append( self.experimentalData[self.__maxDistIdx ,0] + self.__bin/2. )
        self.__edges = np.array(edges, dtype=FLOAT_TYPE)
        # set histogram size
        self.__histogramSize = INT_TYPE( len(self.__edges)-1 )
        # set shell centers and volumes
        self.__shellVolumes = FLOAT_TYPE(4.0/3.)*PI*((self.__edges[1:])**3 - self.__edges[0:-1]**3)
        # set experimental distances and pdf
        self.__experimentalDistances = self.experimentalData[self.__minDistIdx:self.__maxDistIdx +1,0]
        self.__experimentalPDF       = self.experimentalData[self.__minDistIdx:self.__maxDistIdx +1,1]
        # dump to repository
        self._dump_to_repository({'_PairDistributionConstraint__limits'               : self.__limits,
                                  '_PairDistributionConstraint__minDistIdx'           : self.__minDistIdx,
                                  '_PairDistributionConstraint__maxDistIdx'           : self.__maxDistIdx,
                                  '_PairDistributionConstraint__minimumDistance'      : self.__minimumDistance,
                                  '_PairDistributionConstraint__maximumDistance'      : self.__maximumDistance,
                                  '_PairDistributionConstraint__shellCenters'         : self.__shellCenters,
                                  '_PairDistributionConstraint__edges'                : self.__edges,
                                  '_PairDistributionConstraint__histogramSize'        : self.__histogramSize,
                                  '_PairDistributionConstraint__shellVolumes'         : self.__shellVolumes,
                                  '_PairDistributionConstraint__experimentalDistances': self.__experimentalDistances,
                                  '_PairDistributionConstraint__experimentalPDF'      : self.__experimentalPDF})
        # set used dataWeights
        self.__set_used_data_weights(minDistIdx=self.__minDistIdx, maxDistIdx=self.__maxDistIdx )
        # reset constraint
        self.reset_constraint()

    def check_experimental_data(self, experimentalData):
        """
        Check whether experimental data is correct.

        :Parameters:
            #. experimentalData (object): Experimental data to check.

        :Returns:
            #. result (boolean): Whether it is correct or not.
            #. message (str): Checking message that explains whats's
               wrong with the given data.
        """
        if not isinstance(experimentalData, np.ndarray):
            return False, "experimentalData must be a numpy.ndarray"
        if experimentalData.dtype.type is not FLOAT_TYPE:
            return False, "experimentalData type must be %s"%FLOAT_TYPE
        if len(experimentalData.shape) !=2:
            return False, "experimentalData must be of dimension 2"
        if experimentalData.shape[1] !=2:
            return False, "experimentalData must have only 2 columns"
        # check distances order
        inOrder = (np.array(sorted(experimentalData[:,0]), dtype=FLOAT_TYPE)-experimentalData[:,0])<=PRECISION
        if not np.all(inOrder):
            return False, "experimentalData distances are not sorted in order"
        if experimentalData[0][0]<0:
            return False, "experimentalData distances min value is found negative"
        bin  = experimentalData[1,0] -experimentalData[0,0]
        bins = experimentalData[1:,0]-experimentalData[0:-1,0]
        for b in bins:
            if np.abs(b-bin)>PRECISION:
                return False, "experimentalData distances bins are found not coherent"
        # data format is correct
        return True, ""

    def compute_standard_error(self, modelData):
        """
        Compute the standard error (StdErr) as the squared deviations
        between model computed data and the experimental ones.

        .. math::
            StdErr = \\sum \\limits_{i}^{N} W_{i}(Y(X_{i})-F(X_{i}))^{2}

        Where:\n
        :math:`N` is the total number of experimental data points. \n
        :math:`W_{i}` is the data point weight. It becomes equivalent to 1 when dataWeights is set to None. \n
        :math:`Y(X_{i})` is the experimental data point :math:`X_{i}`. \n
        :math:`F(X_{i})` is the computed from the model data  :math:`X_{i}`. \n

        :Parameters:
            #. modelData (numpy.ndarray): The data to compare with the
               experimental one and compute the squared deviation.

        :Returns:
            #. standardError (number): The calculated constraint's
               standardError.
        """
        # compute difference
        diff = self.__experimentalPDF-modelData
        # return squared deviation
        if self._usedDataWeights is None:
            return np.add.reduce((diff)**2)
        else:
            return np.add.reduce(self._usedDataWeights*((diff)**2))

    def __get_total_Gr(self, data, rho0):
        """ This method is created just to speed up the computation
        of the total gr upon fitting.
        """
        # update shape function if needed
        #import time
        #startTime = time.clock()
        Gr = np.zeros(self.__histogramSize, dtype=FLOAT_TYPE)
        for pair in self.__elementsPairs:
            # get weighting scheme
            wij = self.__weightingScheme.get(pair[0]+"-"+pair[1], None)
            if wij is None:
                wij = self.__weightingScheme[pair[1]+"-"+pair[0]]
            # get number of atoms per element
            ni = self.engine.numberOfAtomsPerElement[pair[0]]
            nj = self.engine.numberOfAtomsPerElement[pair[1]]
            # get index of element
            idi = self.engine.elements.index(pair[0])
            idj = self.engine.elements.index(pair[1])
            # get Nij
            if idi == idj:
                Nij = ni*(ni-1)/2.0
                Dij = FLOAT_TYPE( Nij/self.engine.volume )
                nij = data["intra"][idi,idj,:]+data["inter"][idi,idj,:]
                Gr += wij*nij/Dij
            else:
                Nij = ni*nj
                Dij = FLOAT_TYPE( Nij/self.engine.volume )
                nij = data["intra"][idi,idj,:]+data["intra"][idj,idi,:] + data["inter"][idi,idj,:]+data["inter"][idj,idi,:]
                Gr += wij*nij/Dij
        # Divide by shells volume
        Gr /= self.shellVolumes
        # compute total G(r)
        #rho0 = self.engine.numberDensity #(self.engine.numberOfAtoms/self.engine.volume).astype(FLOAT_TYPE)
        Gr   = (4.*PI*self.__shellCenters*rho0)*( Gr-1)
        # remove shape function
        if self._shapeArray is not None:
            Gr -= self._shapeArray
        # Multiply by scale factor
        self._fittedScaleFactor = self.get_adjusted_scale_factor(self.experimentalPDF, Gr, self._usedDataWeights)
        if self._fittedScaleFactor != 1:
            Gr *= FLOAT_TYPE(self._fittedScaleFactor)
        # convolve total with window function
        if self.__windowFunction is not None:
            Gr = np.convolve(Gr, self.__windowFunction, 'same')
        #t = time.clock()-startTime
        #print "%.7f(s) -->  %.7f(Ms)"%(t, 1000000*t)
        return Gr

    def _get_constraint_value(self, data):
        # http://erice2011.docking.org/upload/Other/Billinge_PDF/03-ReadingMaterial/BillingePDF2011.pdf    page 6
        #import time
        #startTime = time.clock()
        #if self._shapeFuncParams is not None and self._shapeArray is None:
        #    self.__set_shape_array()
        output = {}
        for pair in self.__elementsPairs:
            output["rdf_intra_%s-%s" % pair] = np.zeros(self.__histogramSize, dtype=FLOAT_TYPE)
            output["rdf_inter_%s-%s" % pair] = np.zeros(self.__histogramSize, dtype=FLOAT_TYPE)
            output["rdf_total_%s-%s" % pair] = np.zeros(self.__histogramSize, dtype=FLOAT_TYPE)
        gr = np.zeros(self.__histogramSize, dtype=FLOAT_TYPE)
        for pair in self.__elementsPairs:
            # get weighting scheme
            wij = self.__weightingScheme.get(pair[0]+"-"+pair[1], None)
            if wij is None:
                wij = self.__weightingScheme[pair[1]+"-"+pair[0]]
            # get number of atoms per element
            ni = self.engine.numberOfAtomsPerElement[pair[0]]
            nj = self.engine.numberOfAtomsPerElement[pair[1]]
            # get index of element
            idi = self.engine.elements.index(pair[0])
            idj = self.engine.elements.index(pair[1])
            # get Nij
            if idi == idj:
                Nij = FLOAT_TYPE( ni*(ni-1)/2.0 )
                output["rdf_intra_%s-%s" % pair] += data["intra"][idi,idj,:]
                output["rdf_inter_%s-%s" % pair] += data["inter"][idi,idj,:]
            else:
                Nij = FLOAT_TYPE( ni*nj )
                output["rdf_intra_%s-%s" % pair] += data["intra"][idi,idj,:] + data["intra"][idj,idi,:]
                output["rdf_inter_%s-%s" % pair] += data["inter"][idi,idj,:] + data["inter"][idj,idi,:]
            # compute g(r)
            nij = output["rdf_intra_%s-%s" % pair] + output["rdf_inter_%s-%s" % pair]
            dij = nij/self.__shellVolumes
            Dij = Nij/self.engine.volume
            gr += wij*dij/Dij
            # calculate intensityFactor
            intensityFactor = (self.engine.volume*wij)/(Nij*self.__shellVolumes)
            # divide by factor
            output["rdf_intra_%s-%s" % pair] *= intensityFactor
            output["rdf_inter_%s-%s" % pair] *= intensityFactor
            output["rdf_total_%s-%s" % pair]  = output["rdf_intra_%s-%s" % pair] + output["rdf_inter_%s-%s" % pair]
            ## compute g(r) equivalent to earlier gr += wij*dij/Dij
            #gr += output["rdf_total_%s-%s" % pair]
        # compute total G(r)
        rho0 = self.engine.numberDensity #(self.engine.numberOfAtoms/self.engine.volume).astype(FLOAT_TYPE)
        output["pdf_total"] = (4.*PI*self.__shellCenters*rho0) * (gr-1)
        # remove shape function
        if self._shapeArray is not None:
            output["pdf_total"] -= self._shapeArray
        # Multiply by scale factor
        if self.scaleFactor != 1:
            output["pdf_total"] *= self.scaleFactor
        # convolve total with window function
        if self.__windowFunction is not None:
            output["pdf"] = np.convolve(output["pdf_total"], self.__windowFunction, 'same')
        else:
            output["pdf"] = output["pdf_total"]
        #t = time.clock()-startTime
        #print "%.7f(s) -->  %.7f(Ms)"%(t, 1000000*t)
        return output

    def get_constraint_value(self):
        """
        Compute all partial Pair Distribution Functions (PDFs).

        :Returns:
            #. PDFs (dictionary): The PDFs dictionnary, where keys are the
               element wise intra and inter molecular PDFs and values are the
               computed PDFs.
        """
        if self.data is None:
            LOGGER.warn("data must be computed first using 'compute_data' method.")
            return {}
        return self._get_constraint_value(self.data)

    def get_constraint_original_value(self):
        """
        Compute all partial Pair Distribution Functions (PDFs).

        :Returns:
            #. PDFs (dictionary): The PDFs dictionnary, where keys are the
               element wise intra and inter molecular PDFs and values are
               the computed PDFs.
        """
        if self.originalData is None:
            LOGGER.warn("originalData must be computed first using 'compute_data' method.")
            return {}
        return self._get_constraint_value(self.originalData)

    @reset_if_collected_out_of_date
    def compute_data(self):
        """ Compute constraint's data."""
        intra,inter = full_pairs_histograms_coords( boxCoords        = self.engine.boxCoordinates,
                                                    basis            = self.engine.basisVectors,
                                                    isPBC            = self.engine.isPBC,
                                                    moleculeIndex    = self.engine.moleculesIndex,
                                                    elementIndex     = self.engine.elementsIndex,
                                                    numberOfElements = self.engine.numberOfElements,
                                                    minDistance      = self.__minimumDistance,
                                                    maxDistance      = self.__maximumDistance,
                                                    histSize         = self.__histogramSize,
                                                    bin              = self.__bin,
                                                    ncores           = self.engine._runtime_ncores )
        # update data
        self.set_data({"intra":intra, "inter":inter})
        self.set_active_atoms_data_before_move(None)
        self.set_active_atoms_data_after_move(None)
        # set standardError
        totalPDF = self.__get_total_Gr(self.data, rho0=self.engine.numberDensity)
        self.set_standard_error(self.compute_standard_error(modelData = totalPDF))
        # set original data
        if self.originalData is None:
            self._set_original_data(self.data)

    def compute_before_move(self, realIndexes, relativeIndexes):
        """
        Compute constraint before move is executed.

        :Parameters:
            #. realIndexes (numpy.ndarray): Not used here.
            #. relativeIndexes (numpy.ndarray): Group atoms relative index
               the move will be applied to.
        """
        intraM,interM = multiple_pairs_histograms_coords( indexes          = relativeIndexes,
                                                          boxCoords        = self.engine.boxCoordinates,
                                                          basis            = self.engine.basisVectors,
                                                          isPBC            = self.engine.isPBC,
                                                          moleculeIndex    = self.engine.moleculesIndex,
                                                          elementIndex     = self.engine.elementsIndex,
                                                          numberOfElements = self.engine.numberOfElements,
                                                          minDistance      = self.__minimumDistance,
                                                          maxDistance      = self.__maximumDistance,
                                                          histSize         = self.__histogramSize,
                                                          bin              = self.__bin,
                                                          allAtoms         = True,
                                                          ncores           = self.engine._runtime_ncores)
        intraF,interF = full_pairs_histograms_coords( boxCoords        = self.engine.boxCoordinates[relativeIndexes],
                                                      basis            = self.engine.basisVectors,
                                                      isPBC            = self.engine.isPBC,
                                                      moleculeIndex    = self.engine.moleculesIndex[relativeIndexes],
                                                      elementIndex     = self.engine.elementsIndex[relativeIndexes],
                                                      numberOfElements = self.engine.numberOfElements,
                                                      minDistance      = self.__minimumDistance,
                                                      maxDistance      = self.__maximumDistance,
                                                      histSize         = self.__histogramSize,
                                                      bin              = self.__bin,
                                                      ncores           = self.engine._runtime_ncores )
        # set active atoms data
        self.set_active_atoms_data_before_move( {"intra":intraM-intraF, "inter":interM-interF} )
        self.set_active_atoms_data_after_move(None)

    def compute_after_move(self, realIndexes, relativeIndexes, movedBoxCoordinates):
        """
        Compute constraint after move is executed

        :Parameters:
            #. realIndexes (numpy.ndarray): Not used here.
            #. relativeIndexes (numpy.ndarray): Group atoms relative index
               the move will be applied to.
            #. movedBoxCoordinates (numpy.ndarray): The moved atoms new coordinates.
        """
        # change coordinates temporarily
        boxData = np.array(self.engine.boxCoordinates[relativeIndexes], dtype=FLOAT_TYPE)
        self.engine.boxCoordinates[relativeIndexes] = movedBoxCoordinates
        # calculate pair distribution function
        intraM,interM = multiple_pairs_histograms_coords( indexes          = relativeIndexes,
                                                          boxCoords        = self.engine.boxCoordinates,
                                                          basis            = self.engine.basisVectors,
                                                          isPBC            = self.engine.isPBC,
                                                          moleculeIndex    = self.engine.moleculesIndex,
                                                          elementIndex     = self.engine.elementsIndex,
                                                          numberOfElements = self.engine.numberOfElements,
                                                          minDistance      = self.__minimumDistance,
                                                          maxDistance      = self.__maximumDistance,
                                                          histSize         = self.__histogramSize,
                                                          bin              = self.__bin,
                                                          allAtoms         = True,
                                                          ncores           = self.engine._runtime_ncores )
        intraF,interF = full_pairs_histograms_coords( boxCoords        = self.engine.boxCoordinates[relativeIndexes],
                                                      basis            = self.engine.basisVectors,
                                                      isPBC            = self.engine.isPBC,
                                                      moleculeIndex    = self.engine.moleculesIndex[relativeIndexes],
                                                      elementIndex     = self.engine.elementsIndex[relativeIndexes],
                                                      numberOfElements = self.engine.numberOfElements,
                                                      minDistance      = self.__minimumDistance,
                                                      maxDistance      = self.__maximumDistance,
                                                      histSize         = self.__histogramSize,
                                                      bin              = self.__bin,
                                                      ncores           = self.engine._runtime_ncores )
        # set ative atoms data
        self.set_active_atoms_data_after_move( {"intra":intraM-intraF, "inter":interM-interF} )
        # reset coordinates
        self.engine.boxCoordinates[relativeIndexes] = boxData
        # compute and set standardError after move
        dataIntra = self.data["intra"]-self.activeAtomsDataBeforeMove["intra"]+self.activeAtomsDataAfterMove["intra"]
        dataInter = self.data["inter"]-self.activeAtomsDataBeforeMove["inter"]+self.activeAtomsDataAfterMove["inter"]
        totalPDF  = self.__get_total_Gr({"intra":dataIntra, "inter":dataInter}, rho0=self.engine.numberDensity)
        self.set_after_move_standard_error( self.compute_standard_error(modelData = totalPDF) )

    def accept_move(self, realIndexes, relativeIndexes):
        """
        Accept move

        :Parameters:
            #. realIndexes (numpy.ndarray): Not used here.
            #. relativeIndexes (numpy.ndarray): Not used here.
        """
        dataIntra = self.data["intra"]-self.activeAtomsDataBeforeMove["intra"]+self.activeAtomsDataAfterMove["intra"]
        dataInter = self.data["inter"]-self.activeAtomsDataBeforeMove["inter"]+self.activeAtomsDataAfterMove["inter"]
        # change permanently _data
        self.set_data( {"intra":dataIntra, "inter":dataInter} )
        # reset activeAtoms data
        self.set_active_atoms_data_before_move(None)
        self.set_active_atoms_data_after_move(None)
        # update standardError
        self.set_standard_error( self.afterMoveStandardError )
        self.set_after_move_standard_error( None )
        # set new scale factor
        self._set_fitted_scale_factor_value(self._fittedScaleFactor)

    def reject_move(self, realIndexes, relativeIndexes):
        """
        Reject move

        :Parameters:
            #. realIndexes (numpy.ndarray): Not used here.
            #. relativeIndexes (numpy.ndarray): Not used here.
        """
        # reset activeAtoms data
        self.set_active_atoms_data_before_move(None)
        self.set_active_atoms_data_after_move(None)
        # update standardError
        self.set_after_move_standard_error( None )

    def compute_as_if_amputated(self, realIndex, relativeIndex):
        """
        Compute and return constraint's data and standard error as if
        given atom is amputated.

        :Parameters:
            #. realIndex (numpy.ndarray): Atom's index as a numpy array
               of a single element.
            #. relativeIndex (numpy.ndarray): Atom's relative index as a
               numpy array of a single element.
        """
        # compute data
        self.compute_before_move(realIndexes=realIndex, relativeIndexes=relativeIndex)
        dataIntra = self.data["intra"]-self.activeAtomsDataBeforeMove["intra"]
        dataInter = self.data["inter"]-self.activeAtomsDataBeforeMove["inter"]
        data      = {"intra":dataIntra, "inter":dataInter}
        # temporarily adjust self.__weightingScheme
        weightingScheme = self.__weightingScheme
        relativeIndex = relativeIndex[0]
        selectedElement = self.engine.allElements[relativeIndex]
        self.engine.numberOfAtomsPerElement[selectedElement] -= 1
        self.__weightingScheme = get_normalized_weighting(numbers=self.engine.numberOfAtomsPerElement, weights=self._elementsWeight )
        for k, v in self.__weightingScheme.items():
            self.__weightingScheme[k] = FLOAT_TYPE(v)
        # compute standard error
        if not self.engine._RT_moveGenerator.allowFittingScaleFactor:
            SF = self.adjustScaleFactorFrequency
            self._set_adjust_scale_factor_frequency(0)
        rho0          = ((self.engine.numberOfAtoms-1)/self.engine.volume).astype(FLOAT_TYPE)
        totalPDF      = self.__get_total_Gr(data, rho0=rho0)
        standardError = self.compute_standard_error(modelData = totalPDF)
        if not self.engine._RT_moveGenerator.allowFittingScaleFactor:
            self._set_adjust_scale_factor_frequency(SF)
        # reset activeAtoms data
        self.set_active_atoms_data_before_move(None)
        # set data
        self.set_amputation_data( {'data':data, 'weightingScheme':self.__weightingScheme} )
        self.set_amputation_standard_error( standardError )
        # reset weightingScheme
        self.__weightingScheme = weightingScheme
        self.engine.numberOfAtomsPerElement[selectedElement] += 1

    def accept_amputation(self, realIndex, relativeIndex):
        """
        Accept amputated atom and sets constraints data and standard error accordingly.

        :Parameters:
            #. realIndex (numpy.ndarray): Not used here.
            #. relativeIndex (numpy.ndarray): Not used here.
        """
        self.set_data( self.amputationData['data'] )
        self.__weightingScheme = self.amputationData['weightingScheme']
        self.set_standard_error( self.amputationStandardError )
        self.set_amputation_data( None )
        self.set_amputation_standard_error( None )
        # set new scale factor
        self._set_fitted_scale_factor_value(self._fittedScaleFactor)

    def reject_amputation(self, realIndex, relativeIndex):
        """
        Reject amputated atom and set constraint's data and standard
        error accordingly.

        :Parameters:
            #. realIndex (numpy.ndarray): Not used here.
            #. relativeIndex (numpy.ndarray): Not used here.
        """
        self.set_amputation_data( None )
        self.set_amputation_standard_error( None )

    def _on_collector_collect_atom(self, realIndex):
        pass

    def _on_collector_release_atom(self, realIndex):
        pass

    def plot(self, ax=None, intra=True, inter=True, shapeFunc=True,
                   xlabel=True, xlabelSize=16,
                   ylabel=True, ylabelSize=16,
                   legend=True, legendCols=2, legendLoc='best',
                   title=True, titleStdErr=True,
                   titleScaleFactor=True, titleAtRem=True,
                   titleUsedFrame=True, show=True):
        """
        Plot pair distribution constraint.

        :Parameters:
            #. ax (None, matplotlib Axes): matplotlib Axes instance to plot in.
               If None is given a new plot figure will be created.
            #. intra (boolean): Whether to add intra-molecular pair
               distribution function features to the plot.
            #. inter (boolean): Whether to add inter-molecular pair
               distribution function features to the plot.
            #. shapeFunc (boolean): Whether to add shape function to the plot
               only when exists.
            #. xlabel (boolean): Whether to create x label.
            #. xlabelSize (number): The x label font size.
            #. ylabel (boolean): Whether to create y label.
            #. ylabelSize (number): The y label font size.
            #. legend (boolean): Whether to create the legend or not
            #. legendCols (integer): Legend number of columns.
            #. legendLoc (string): The legend location. Anything among
               'right', 'center left', 'upper right', 'lower right', 'best',
               'center', 'lower left', 'center right', 'upper left',
               'upper center', 'lower center' is accepted.
            #. title (boolean): Whether to create the title or not.
            #. titleStdErr (boolean): Whether to show constraint standard
               error value in title.
            #. titleScaleFactor (boolean): Whether to show contraint's scale
               factor value in title.
            #. titleAtRem (boolean): Whether to show engine's number of
               removed atoms.
            #. titleUsedFrame(boolean): Whether to show used frame name
               in title.
            #. show (boolean): Whether to render and show figure before
               returning.

        :Returns:
            #. figure (matplotlib Figure): matplotlib used figure.
            #. axes (matplotlib Axes): matplotlib used axes.

        +----------------------------------------------------------------------+
        |.. figure:: pair_distribution_constraint_plot_method.png              |
        |   :width: 530px                                                      |
        |   :height: 400px                                                     |
        |   :align: left                                                       |
        +----------------------------------------------------------------------+
        """
        # get constraint value
        output = self.get_constraint_value()
        if not len(output):
            LOGGER.warn("%s constraint data are not computed."%(self.__class__.__name__))
            return
        # import matplotlib
        import matplotlib.pyplot as plt
        # get axes
        if ax is None:
            FIG  = plt.figure()
            AXES = plt.gca()
        else:
            AXES = ax
            FIG  = AXES.get_figure()
        # Create plotting styles
        COLORS  = ["b",'g','r','c','y','m']
        MARKERS = ["",'.','+','^','|']
        INTRA_STYLES = [r[0] + r[1]for r in itertools.product(['--'], list(reversed(COLORS)))]
        INTRA_STYLES = [r[0] + r[1]for r in itertools.product(MARKERS, INTRA_STYLES)]
        INTER_STYLES = [r[0] + r[1]for r in itertools.product(['-'], COLORS)]
        INTER_STYLES = [r[0] + r[1]for r in itertools.product(MARKERS, INTER_STYLES)]
        # plot experimental
        AXES.plot(self.experimentalDistances,self.experimentalPDF, 'ro', label="experimental", markersize=7.5, markevery=1 )
        AXES.plot(self.shellCenters, output["pdf"], 'k', linewidth=3.0,  markevery=25, label="total" )
        # plot without window function
        if self.windowFunction is not None:
            AXES.plot(self.shellCenters, output["pdf_total"], 'k', linewidth=1.0,  markevery=5, label="total - no window" )
        if shapeFunc and self._shapeArray is not None:
            AXES.plot(self.shellCenters, self._shapeArray, '--k', linewidth=1.0,  markevery=5, label="shape function" )
        # plot partials
        intraStyleIndex = 0
        interStyleIndex = 0
        for key, val in output.items():
            if key in ("pdf_total", "pdf"):
                continue
            elif "intra" in key and intra:
                AXES.plot(self.shellCenters, val, INTRA_STYLES[intraStyleIndex], markevery=5, label=key )
                intraStyleIndex+=1
            elif "inter" in key and inter:
                AXES.plot(self.shellCenters, val, INTER_STYLES[interStyleIndex], markevery=5, label=key )
                interStyleIndex+=1
        # plot legend
        if legend:
            AXES.legend(frameon=False, ncol=legendCols, loc=legendLoc)
        # set title
        if title:
            FIG.canvas.set_window_title('Pair Distribution Constraint')
            if titleUsedFrame:
                t = '$frame: %s$ : '%self.engine.usedFrame.replace('_','\_')
            else:
                t = ''
            if titleAtRem:
                t += "$%i$ $rem.$ $at.$ - "%(len(self.engine._atomsCollector))
            if titleStdErr and self.standardError is not None:
                t += "$std$ $error=%.6f$ "%(self.standardError)
            if titleScaleFactor:
                t += " - "*(len(t)>0) + "$scale$ $factor=%.6f$"%(self.scaleFactor)
            if len(t):
                AXES.set_title(t)
        # set axis labels
        if xlabel:
            AXES.set_xlabel("$r(\AA)$", size=xlabelSize)
        if ylabel:
            AXES.set_ylabel("$G(r)(\AA^{-2})$"  , size=ylabelSize)
        # set background color
        FIG.patch.set_facecolor('white')
        #show
        if show:
            plt.show()
        # return axes
        return FIG, AXES

    def export(self, fname, format='%12.5f', delimiter=' ', comments='# '):
        """
        Export pair distribution constraint data.

        :Parameters:
            #. fname (path): full file name and path.
            #. format (string): string format to export the data.
               format is as follows (%[flag]width[.precision]specifier)
            #. delimiter (string): String or character separating columns.
            #. comments (string): String that will be prepended to the header.
        """
        # get constraint value
        output = self.get_constraint_value()
        if not len(output):
            LOGGER.warn("%s constraint data are not computed."%(self.__class__.__name__))
            return
        # start creating header and data
        header = ["distances",]
        data   = [self.experimentalDistances,]
        # add all intra data
        for key, val in output.items():
            if "inter" in key:
                continue
            header.append(key.replace(" ","_"))
            data.append(val)
        # add all inter data
        for key, val in output.items():
            if "intra" in key:
                continue
            header.append(key.replace(" ","_"))
            data.append(val)
        # add total
        header.append("total")
        data.append(output["pdf"])
        if self.windowFunction is not None:
            header.append("total_no_window")
            data.append(output["pdf_total"])
        if self._shapeArray is not None:
            header.append("shape_function")
            data.append(self._shapeArray)
        # add experimental data
        header.append("experimental")
        data.append(self.experimentalPDF)
        # create array and export
        data =np.transpose(data).astype(float)
        # save
        np.savetxt(fname     = fname,
                   X         = data,
                   fmt       = format,
                   delimiter = delimiter,
                   header    = " ".join(header),
                   comments  = comments)
