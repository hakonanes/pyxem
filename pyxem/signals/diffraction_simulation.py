import numpy as np
from hyperspy._components.expression import Expression
from pymatgen.util.plotting import pretty_plot
from pyxem.signals.electron_diffraction import ElectronDiffraction


_GAUSSIAN2D_EXPR = \
    "intensity * exp(" \
    "-((x-cx)**2 / (2 * sigma ** 2)" \
    " + (y-cy)**2 / (2 * sigma ** 2))" \
    ")"


class DiffractionSimulation:
    """Holds the result of a given diffraction pattern.

    Parameters
    ----------

    coordinates : array-like, shape [n_points, 2]
        The x-y coordinates of points in reciprocal space.
    indices : array-like, shape [n_points, 3]
        The indices of the reciprocal lattice points that intersect the
        Ewald sphere.
    intensities : array-like, shape [n_points, ]
        The intensity of the reciprocal lattice points.
    calibration : float or tuple of float, optional
        The x- and y-scales of the pattern, with respect to the original
        reciprocal angstrom coordinates.
    offset : tuple of float, optional
        The x-y offset of the pattern in reciprocal angstroms. Defaults to
        zero in each direction.
    """

    def __init__(self, coordinates=None, indices=None, intensities=None,
                 calibration=1., offset=(0., 0.), with_direct_beam=False):
        """Initializes the DiffractionSimulation object with data values for
        the coordinates, indices, intensities, calibration and offset.
        """
        self._coordinates = None
        self.coordinates = coordinates
        self.indices = indices
        self._intensities = None
        self.intensities = intensities
        self._calibration = (1., 1.)
        self.calibration = calibration
        self.offset = offset
        self.with_direct_beam = with_direct_beam

    @property
    def calibrated_coordinates(self):
        """ndarray : Coordinates converted into pixel space."""
        coordinates = np.copy(self.coordinates)
        coordinates[:, 0] += self.offset[0]
        coordinates[:, 1] += self.offset[1]
        coordinates[:, 0] /= self.calibration[0]
        coordinates[:, 1] /= self.calibration[1]
        return coordinates

    @property
    def calibration(self):
        """tuple of float : The x- and y-scales of the pattern, with respect to
        the original reciprocal angstrom coordinates."""
        return self._calibration

    @calibration.setter
    def calibration(self, calibration):
        if np.all(np.equal(calibration, 0)):
            raise ValueError("`calibration` cannot be zero.")
        if isinstance(calibration, float) or isinstance(calibration, int):
            self._calibration = (calibration, calibration)
        elif len(calibration) == 2:
            self._calibration = calibration
        else:
            raise ValueError("`calibration` must be a float or length-2"
                             "tuple of floats.")

    @property
    def direct_beam_mask(self):
        """ndarray : If `with_direct_beam` is True, returns a True array for all
        points. If `with_direct_beam` is False, returns a True array with False
        in the position of the direct beam."""
        if self.with_direct_beam:
            return np.ones_like(self._intensities, dtype=bool)
        else:
            return np.any(self._coordinates, axis=1)

    @property
    def coordinates(self):
        """ndarray : The coordinates of all unmasked points."""
        if self._coordinates is None:
            return None
        return self._coordinates[self.direct_beam_mask]

    @coordinates.setter
    def coordinates(self, coordinates):
        self._coordinates = coordinates

    @property
    def intensities(self):
        """ndarray : The intensities of all unmasked points."""
        if self._intensities is None:
            return None
        return self._intensities[self.direct_beam_mask]

    @intensities.setter
    def intensities(self, intensities):
        self._intensities = intensities

    def plot_simulated_pattern(self, ax=None):
        """Plots the simulated electron diffraction pattern with a logarithmic
        intensity scale.

        Run `.show()` on the result of this method to display the plot.

        Parameters
        ----------
        ax : :obj:`matplotlib.axes.Axes`, optional
            A `matplotlib` axes instance. Used if the plot needs to be in a
            figure that has been created elsewhere.

        """
        if ax is None:
            plt = pretty_plot(10, 10)
            ax = plt.gca()
        ax.scatter(
            self.coordinates[:, 0],
            self.coordinates[:, 1],
            s=np.log2(self.intensities)
        )
        ax.set_xlabel("Reciprocal Dimension ($A^{-1}$)")
        ax.set_ylabel("Reciprocal Dimension ($A^{-1}$)")
        return ax

    def as_signal(self, size, sigma, max_r, mode='qual'):
        """Returns the diffraction data as an ElectronDiffraction signal with
        two-dimensional Gaussians representing each diffracted peak.

        Parameters
        ----------
        size : int
            Side length (in pixels) for the signal to be simulated.
        sigma : float
            Standard deviation of the Gaussian function to be plotted.
        max_r : float
            Half the side length in reciprocal Angstroms. Defines the signal's
            calibration
        mode  : 'qual','quant' or 'legacy'
            In 'qual' mode the peaks are discretized and then broadened. This is
            faster. In 'quant' mode 'electrons' are fired from exact peak location
            and then assinged to 'detectors'. This is slower but more correct.

        """
        l,delta_l = np.linspace(-max_r, max_r, size,retstep=True)
        coords = self.coordinates[:, :2]
        if mode == 'legacy':
            dp_dat = 0
            x, y = np.meshgrid(l, l)
            g = Expression(_GAUSSIAN2D_EXPR, 'Gaussian2D', module='numexpr')
            for (cx, cy), intensity in zip(coords, self.intensities):
                g.intensity.value = intensity
                g.sigma.value = sigma
                g.cx.value = cx
                g.cy.value = cy
                dp_dat += g.function(x, y)
        elif mode == 'qual':
            dp_dat = np.zeros([size,size])
            coords = np.hstack((coords,self.intensities.reshape(len(self.intensities),-1))) #attaching int to coords
            coords = coords[np.logical_and(coords[:,0]<max_r,coords[:,0]>-max_r)]
            coords = coords[np.logical_and(coords[:,1]<max_r,coords[:,1]>-max_r)]
            x,y = (coords)[:,0] , (coords)[:,1]
            num = np.digitize(x,l,right=True),np.digitize(y,l,right=True)
            dp_dat[num] = coords[:,2] #using the intensities
            from skimage.filters import gaussian as point_spread
            dp_dat = point_spread(dp_dat,sigma=sigma/delta_l) #sigma in terms of pixels
        elif mode == 'quant':
            var = np.power(sigma,2)
            electron_array = False
            ss = 75 #sample size to be multiplied by intensity
            peak_location_detailed = np.hstack((coords,(self.intensities.reshape(len(self.intensities),1))))
            for peak in peak_location_detailed:
                if type(electron_array) == np.ndarray:
                    electron_array_2 = np.random.multivariate_normal(peak[:2],(var)*np.eye(2,2),size=ss*np.rint(peak[2]).astype(int))
                    electron_array = np.vstack((electron_array,electron_array_2))
                else:
                    electron_array = np.random.multivariate_normal(peak[:2],(var)*np.eye(2,2),size=ss*np.rint(peak[2]).astype(int))
            dp_dat = np.zeros([size,size])
            ## chuck electrons that go to far out
            electron_array = electron_array[np.logical_and(electron_array[:,0]<max_r,electron_array[:,0]>-max_r)]
            electron_array = electron_array[np.logical_and(electron_array[:,1]<max_r,electron_array[:,1]>-max_r)]
            x_num,y_num = np.digitize(electron_array[:,0],l,right=True),np.digitize(electron_array[:,1],l,right=True)
            for i in np.arange(len(x_num)):
                dp_dat[x_num[i],y_num[i]] += 1

        dp_dat = dp_dat/np.max(dp_dat) #normalise to unit intensity
        dp = ElectronDiffraction(dp_dat)
        dp.set_calibration(2*max_r/size)

        return dp


