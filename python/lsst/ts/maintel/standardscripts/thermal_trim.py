# This file is part of ts_maintel_standardscripts.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Thermal-focus trim prediction for the main telescope.

The degree-of-freedom (DOF) trim that corrects focus is predicted from
thermal telemetry. The correction was derived from over 60k LSSTCam science
visits, where the open-loop v-mode-1 (v1) amplitude was determined from the
DOF trim minus the value measured from the CWFS wavefront. v1 was then
modeled with a robust (Huber) linear fit to the mean TMA truss temperature
and the M1M3 bulk thermal gradients along z, radial, x and y.

The thermal telemetry comes from the ESS CSC, via the EFD:

* The truss temperature is the mean of the ``+X/+Y Truss Structure`` and
  ``-X/-Y Truss Structure`` channels of the ``ESS.temperature`` telemetry
  published by the M2 hexapod temperature readout, ESS:122 (see
  ``ESS/v8/_init.yaml`` in ts_config_ocs).
* The M1M3 gradients are the ``ESS.m1m3ThermalGradients`` telemetry, fitted
  by ts_m1m3_utils from the M1M3 thermal scanners and published by ESS:114.

Every fitted coefficient lives in ``thermal_trim_coefficients.yaml`` next to
this module, read by `TrimCalculator` at construction.
"""

__all__ = [
    "DEFAULT_COEFFICIENT_PATH",
    "DEFAULT_GRADIENTS_SAL_INDEX",
    "DEFAULT_TRUSS_SAL_INDEX",
    "DEFAULT_TRUSS_TEMPERATURE_ITEMS",
    "GRADIENT_FIELDS",
    "ThermalTelemetry",
    "TrimCalculator",
    "get_efd_client",
    "get_thermal_telemetry",
]

import dataclasses
import logging
import os
import pathlib
import typing

import numpy as np
import yaml
from astropy.time import Time, TimeDelta
from lsst.ts.observatory.control.utils.enums import DOFName

from .set_dof import EFD_NAMES

try:
    from lsst_efd_client import EfdClient
except ImportError:
    EfdClient = None

#: Default coefficient file, alongside this module.
DEFAULT_COEFFICIENT_PATH = (
    pathlib.Path(__file__).resolve().parent / "thermal_trim_coefficients.yaml"
)

#: ESS index that publishes the TMA truss temperatures (M2 hexapod readout).
DEFAULT_TRUSS_SAL_INDEX = 122

#: ``temperatureItem`` channels of ESS:122 holding the +X/+Y and -X/-Y truss
#: structure temperatures.
DEFAULT_TRUSS_TEMPERATURE_ITEMS = (6, 7)

#: ESS index that publishes ``m1m3ThermalGradients``.
DEFAULT_GRADIENTS_SAL_INDEX = 114

#: ``m1m3ThermalGradients`` field for each gradient axis.
GRADIENT_FIELDS = {
    "x": "xGradient",
    "y": "yGradient",
    "z": "zGradient",
    "radial": "radialGradient",
}

TRUSS_TOPIC = "lsst.sal.ESS.temperature"
GRADIENTS_TOPIC = "lsst.sal.ESS.m1m3ThermalGradients"


@dataclasses.dataclass
class ThermalTelemetry:
    """Thermal telemetry averaged over a lookback window.

    Attributes
    ----------
    truss_temp_c : `float`
        Mean TMA truss temperature [deg C].
    truss_n_samples : `int`
        Number of truss temperature samples averaged.
    truss_age : `float`
        Age of the most recent truss sample when queried [s].
    gradients : `dict` [`str`, `float`] or `None`
        Mean M1M3 thermal gradients keyed ``x``, ``y``, ``z`` and
        ``radial`` [deg C per m], or `None` if unavailable.
    gradients_n_samples : `int`
        Number of gradient samples averaged.
    gradients_age : `float` or `None`
        Age of the most recent gradient sample when queried [s], or `None`
        if unavailable.
    """

    truss_temp_c: float
    truss_n_samples: int
    truss_age: float
    gradients: dict[str, float] | None = None
    gradients_n_samples: int = 0
    gradients_age: float | None = None

    #: Configuration key for each gradient axis, see `from_config`.
    GRADIENT_CONFIG_KEYS: typing.ClassVar[dict[str, str]] = {
        "x": "x_gradient_c_per_m",
        "y": "y_gradient_c_per_m",
        "z": "z_gradient_c_per_m",
        "radial": "radial_gradient_c_per_m",
    }

    @classmethod
    def from_config(cls, config: typing.Mapping[str, typing.Any]) -> "ThermalTelemetry":
        """Build telemetry from user-supplied values.

        Parameters
        ----------
        config : `Mapping`
            ``truss_temp_c`` [deg C] and, optionally, the four gradients
            ``x_gradient_c_per_m``, ``y_gradient_c_per_m``,
            ``z_gradient_c_per_m`` and ``radial_gradient_c_per_m`` [deg C
            per m]. The gradients are only used if all four are given and
            not `None`; otherwise they are reported unavailable.

        Returns
        -------
        `ThermalTelemetry`
            Telemetry with one sample of age zero per quantity.
        """
        telemetry = cls(
            truss_temp_c=float(config["truss_temp_c"]),
            truss_n_samples=1,
            truss_age=0.0,
        )
        values = {
            axis: config.get(key) for axis, key in cls.GRADIENT_CONFIG_KEYS.items()
        }
        if all(value is not None for value in values.values()):
            telemetry.gradients = {axis: float(value) for axis, value in values.items()}
            telemetry.gradients_n_samples = 1
            telemetry.gradients_age = 0.0
        return telemetry


class TrimCalculator:
    """The fitted thermal-focus correction, read from a coefficient file.

    Parameters
    ----------
    path : `str` or `pathlib.Path`, optional
        Coefficient file to read. Defaults to `DEFAULT_COEFFICIENT_PATH`.

    Attributes
    ----------
    coefficients : `dict`
        The coefficient file as parsed.
    intercept_um : `float`
        Response with every feature at zero [um of equivalent hexapod dz].
    truss_um_per_c : `float`
        Coefficient on the TMA truss temperature [um of equivalent hexapod
        dz per deg C].
    gradient_um_per_c_per_m : `dict`
        Coefficients on the four M1M3 bulk thermal gradients, keyed ``z``,
        ``y``, ``radial`` and ``x`` [um of equivalent hexapod dz per (deg C
        per m)].
    sample_feature_range : `dict`
        Full observed range of each feature over the fitted sample, as
        ``(low, high)``. Truss temperature in deg C, the four gradients in
        deg C per m.
    v1_per_um_dz : `float`
        v-mode-1 amplitude per um of total hexapod dz travel, split evenly
        between the camera and M2 hexapods [dimensionless per um].
    dz_um_per_um_wf : `float`
        Equivalent hexapod dz per um of wavefront defocus [um of equivalent
        hexapod dz per um of wavefront].
    v1_dof_um_per_unit : `dict`
        DOF content of one unit of v-mode-1 amplitude, keyed by `DOFName`
        name [um per unit v1].
    v1_dof_labels : `tuple`
        ``(name, label, unit)`` for each entry of `v1_dof_um_per_unit`.
    v1_dof_vector : `numpy.ndarray`
        `v1_dof_um_per_unit` as a 50-element DOF vector [um per unit v1].
    """

    #: Feature names, in the order `predict_trim` takes them.
    FEATURES = (
        "truss_temp_c",
        "z_gradient_c_per_m",
        "y_gradient_c_per_m",
        "radial_gradient_c_per_m",
        "x_gradient_c_per_m",
    )

    def __init__(self, path: str | pathlib.Path | None = None) -> None:
        self.path = pathlib.Path(DEFAULT_COEFFICIENT_PATH if path is None else path)
        with open(self.path) as handle:
            coefficients = yaml.safe_load(handle)

        self.coefficients = coefficients
        self.intercept_um = float(coefficients["intercept_um"])
        self.truss_um_per_c = float(coefficients["truss_um_per_c"])
        self.gradient_um_per_c_per_m = {
            axis: float(value)
            for axis, value in coefficients["gradient_um_per_c_per_m"].items()
        }
        self.sample_feature_range = {
            name: (float(lo), float(hi))
            for name, (lo, hi) in coefficients["sample_feature_range"].items()
        }
        self.v1_per_um_dz = float(coefficients["v1_per_um_dz"])
        self.dz_um_per_um_wf = float(coefficients["dz_um_per_um_wf"])

        dof = coefficients["v1_dof"]
        self.v1_dof_um_per_unit = {
            name: float(entry["um_per_unit"]) for name, entry in dof.items()
        }
        self.v1_dof_labels = tuple(
            (name, entry["label"], entry["unit"]) for name, entry in dof.items()
        )
        self.v1_dof_vector = np.zeros(len(DOFName))
        for name, value in self.v1_dof_um_per_unit.items():
            self.v1_dof_vector[DOFName[name]] = value

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self.path)!r})"

    def extrapolated_features(self, **features: float) -> list[str]:
        """Return the names of the given features outside the fitted range.

        Parameters
        ----------
        **features : `float`
            Feature values keyed by name, see `FEATURES`.

        Returns
        -------
        `list` [`str`]
            Description of each feature outside `sample_feature_range`.
        """
        outside = []
        for name, value in features.items():
            lo, hi = self.sample_feature_range[name]
            if value < lo or value > hi:
                outside.append(f"{name}={value:+.5f} outside [{lo:+.5f}, {hi:+.5f}]")
        return outside

    def predict_trim(
        self,
        truss_temp_c: float,
        z_gradient_c_per_m: float = 0.0,
        y_gradient_c_per_m: float = 0.0,
        radial_gradient_c_per_m: float = 0.0,
        x_gradient_c_per_m: float = 0.0,
    ) -> tuple[float, float, dict[str, float]]:
        """Predict the focus v-mode and the DOF trim from thermal telemetry.

        Parameters
        ----------
        truss_temp_c : `float`
            TMA truss temperature, the mean of the two thermometers [deg C].
        z_gradient_c_per_m, y_gradient_c_per_m, radial_gradient_c_per_m, \
x_gradient_c_per_m : `float`, optional
            M1M3 bulk thermal gradients [deg C per m]. Default to zero,
            which yields the truss-only prediction.

        Returns
        -------
        v1 : `float`
            Predicted v-mode-1 amplitude [dimensionless].
        v1_dz : `float`
            The same prediction as focus [um of equivalent hexapod dz, split
            evenly between the camera and M2 hexapods].
        dof_dict : `dict` [`str`, `float`]
            DOF trim keyed by `DOFName` name [um].
        """
        grad = self.gradient_um_per_c_per_m
        v1_dz = (
            self.intercept_um
            + self.truss_um_per_c * truss_temp_c
            + grad["z"] * z_gradient_c_per_m
            + grad["y"] * y_gradient_c_per_m
            + grad["radial"] * radial_gradient_c_per_m
            + grad["x"] * x_gradient_c_per_m
        )
        v1 = v1_dz * self.v1_per_um_dz
        dof_dict = {name: value * v1 for name, value in self.v1_dof_um_per_unit.items()}
        return float(v1), float(v1_dz), dof_dict

    def predict_from_telemetry(
        self, telemetry: ThermalTelemetry
    ) -> tuple[float, float, dict[str, float]]:
        """Predict the focus v-mode and the DOF trim from `ThermalTelemetry`.

        If the telemetry has no gradients, the truss-only prediction (all
        gradients at zero) is returned.

        Parameters
        ----------
        telemetry : `ThermalTelemetry`
            Averaged thermal telemetry.

        Returns
        -------
        v1, v1_dz, dof_dict
            See `predict_trim`.
        """
        return self.predict_trim(**self.features_from_telemetry(telemetry))

    @staticmethod
    def features_from_telemetry(telemetry: ThermalTelemetry) -> dict[str, float]:
        """Return the `predict_trim` features for `ThermalTelemetry`.

        Missing gradients are zero.
        """
        gradients = telemetry.gradients or {}
        return dict(
            truss_temp_c=telemetry.truss_temp_c,
            z_gradient_c_per_m=gradients.get("z", 0.0),
            y_gradient_c_per_m=gradients.get("y", 0.0),
            radial_gradient_c_per_m=gradients.get("radial", 0.0),
            x_gradient_c_per_m=gradients.get("x", 0.0),
        )

    def v1_from_dof(self, aggregated_dof: typing.Sequence[float]) -> float:
        """Project a DOF state onto v-mode-1.

        Parameters
        ----------
        aggregated_dof : `Sequence` [`float`]
            50-element DOF state, e.g. ``aggregatedDoF`` from the MTAOS
            ``degreeOfFreedom`` event.

        Returns
        -------
        `float`
            v-mode-1 amplitude of the state [dimensionless].
        """
        state = np.asarray(aggregated_dof, dtype=float)
        if state.shape != self.v1_dof_vector.shape:
            raise ValueError(
                f"Expected {self.v1_dof_vector.size} DOF values, got {state.size}."
            )
        return float(
            np.dot(state, self.v1_dof_vector)
            / np.dot(self.v1_dof_vector, self.v1_dof_vector)
        )

    def dof_offset(
        self, v1_target: float, aggregated_dof: typing.Sequence[float]
    ) -> np.ndarray:
        """Compute the DOF offset that moves a state to a v-mode-1 amplitude.

        Only the v-mode-1 component of the state is changed; everything
        orthogonal to it is left alone.

        Parameters
        ----------
        v1_target : `float`
            Target v-mode-1 amplitude, e.g. from `predict_trim`.
        aggregated_dof : `Sequence` [`float`]
            Current 50-element DOF state.

        Returns
        -------
        `numpy.ndarray`
            50-element DOF offset to apply [um or arcsec, per DOF].
        """
        return (v1_target - self.v1_from_dof(aggregated_dof)) * self.v1_dof_vector


def get_efd_client() -> typing.Any:
    """Return an EFD client for the current site.

    Returns
    -------
    `lsst_efd_client.EfdClient`
        Client instance to query the EFD.

    Raises
    ------
    RuntimeError
        If ``lsst_efd_client`` is not installed or ``LSST_SITE`` does not
        name a known EFD.
    """
    if EfdClient is None:
        raise RuntimeError("Could not import lsst_efd_client library.")
    site = os.environ.get("LSST_SITE")
    if site is None:
        raise RuntimeError("LSST_SITE environment variable not defined.")
    if site not in EFD_NAMES:
        raise RuntimeError(f"No EFD name for {site=}.")
    return EfdClient(EFD_NAMES[site])


def _age(data: typing.Any, now: Time) -> float:
    """Return the age of the last row of a time-indexed DataFrame [s]."""
    return float((now - Time(data.index[-1])).sec)


async def get_thermal_telemetry(
    efd_client: typing.Any,
    lookback: float = 600.0,
    max_data_age: float = 900.0,
    truss_sal_index: int = DEFAULT_TRUSS_SAL_INDEX,
    truss_temperature_items: typing.Sequence[int] = DEFAULT_TRUSS_TEMPERATURE_ITEMS,
    gradients_sal_index: int = DEFAULT_GRADIENTS_SAL_INDEX,
    log: logging.Logger | None = None,
) -> ThermalTelemetry:
    """Query the EFD for the truss temperature and M1M3 thermal gradients.

    Each quantity is averaged over the lookback window ending now.

    Parameters
    ----------
    efd_client : `lsst_efd_client.EfdClient`
        EFD client.
    lookback : `float`, optional
        Length of the window to average [s].
    max_data_age : `float`, optional
        Telemetry whose most recent sample is older than this is treated as
        unavailable [s].
    truss_sal_index : `int`, optional
        ESS index publishing the truss temperatures.
    truss_temperature_items : `Sequence` [`int`], optional
        ``temperatureItem`` channels holding the truss temperatures.
    gradients_sal_index : `int`, optional
        ESS index publishing ``m1m3ThermalGradients``.
    log : `logging.Logger`, optional
        Logger for diagnostics.

    Returns
    -------
    `ThermalTelemetry`
        The averaged telemetry. ``gradients`` is `None` if the M1M3
        gradients are missing, stale or not finite.

    Raises
    ------
    RuntimeError
        If the truss temperature is missing, stale or not finite.
    """
    log = logging.getLogger(__name__) if log is None else log
    now = Time.now()
    start = now - TimeDelta(lookback, format="sec")

    truss_fields = [f"temperatureItem{item}" for item in truss_temperature_items]
    truss = await efd_client.select_time_series(
        TRUSS_TOPIC, truss_fields, start, now, index=truss_sal_index
    )
    if truss.empty:
        raise RuntimeError(
            f"No truss temperature from ESS:{truss_sal_index} in the last {lookback} s."
        )
    truss_age = _age(truss, now)
    if truss_age > max_data_age:
        raise RuntimeError(
            f"Truss temperature from ESS:{truss_sal_index} is {truss_age:.0f} s old, "
            f"older than {max_data_age} s."
        )
    truss_values = truss[truss_fields].to_numpy(dtype=float)
    truss_temp_c = float(np.nanmean(truss_values))
    if not np.isfinite(truss_temp_c):
        raise RuntimeError(
            f"Truss temperature from ESS:{truss_sal_index} is not finite."
        )
    telemetry = ThermalTelemetry(
        truss_temp_c=truss_temp_c,
        truss_n_samples=len(truss),
        truss_age=truss_age,
    )

    gradient_fields = list(GRADIENT_FIELDS.values())
    gradients = await efd_client.select_time_series(
        GRADIENTS_TOPIC, gradient_fields, start, now, index=gradients_sal_index
    )
    if gradients.empty:
        log.warning(
            f"No M1M3 thermal gradients from ESS:{gradients_sal_index} "
            f"in the last {lookback} s."
        )
        return telemetry
    gradients = gradients.dropna(subset=gradient_fields)
    if gradients.empty:
        log.warning(
            f"M1M3 thermal gradients from ESS:{gradients_sal_index} are all nan."
        )
        return telemetry
    gradients_age = _age(gradients, now)
    if gradients_age > max_data_age:
        log.warning(
            f"M1M3 thermal gradients from ESS:{gradients_sal_index} are "
            f"{gradients_age:.0f} s old, older than {max_data_age} s."
        )
        return telemetry
    means = gradients[gradient_fields].to_numpy(dtype=float).mean(axis=0)
    if not np.all(np.isfinite(means)):
        log.warning(
            f"M1M3 thermal gradients from ESS:{gradients_sal_index} are not finite."
        )
        return telemetry
    telemetry.gradients = {
        axis: float(means[i]) for i, axis in enumerate(GRADIENT_FIELDS)
    }
    telemetry.gradients_n_samples = len(gradients)
    telemetry.gradients_age = gradients_age
    return telemetry
