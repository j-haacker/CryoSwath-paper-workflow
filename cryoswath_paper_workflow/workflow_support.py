from contextlib import contextmanager
from configparser import ConfigParser
from dataclasses import dataclass
import fnmatch
import netrc as netrc_mod
import os
from pathlib import Path
from typing import Any, Callable, Literal

import sys
import threading
import warnings

import cryoswath.misc as cryoswath_misc
from cryoswath.misc import load_glacier_outlines
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
from statsmodels.tsa.deterministic import CalendarFourier, TimeTrend
from statsmodels.tsa.seasonal import seasonal_decompose
from tqdm import tqdm
import xarray as xr
import yaml


_ESA_AUTH_IDP_HOST = "eoiam-idp.eo.esa.int"
_ESA_CS2_HOST = "science-pds.cryosat.esa.int"
_ESA_CRYOSWATH_KEYRING_SERVICE = "cryoswath.esa"
_ESA_ENV_USER = "EOIAM_USER"
_ESA_ENV_PASSWORD = "EOIAM_PASSWORD"
_MAAP_TOKEN_ENV = "ESA_MAAP_OFFLINE_TOKEN"
_ESA_KEYRING_SERVICE_CANDIDATES = (
    _ESA_AUTH_IDP_HOST,
    _ESA_CS2_HOST,
    _ESA_CRYOSWATH_KEYRING_SERVICE,
)
_ESA_KEYRING_DEFAULT_USER_KEYS = (
    "__default_user__",
    "default_user",
    "username",
)


@dataclass(frozen=True)
class EsaCredentialStatus:
    available: bool
    source: str | None = None
    notes: tuple[str, ...] = ()


def _is_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").is_file() and (path / "Snakefile").is_file()


def _candidate_roots(start: Path):
    start = start.resolve()
    if start.is_file():
        start = start.parent
    yield start
    yield from start.parents


def _find_project_root() -> Path:
    for start in (Path(__file__), Path.cwd()):
        for candidate in _candidate_roots(start):
            if _is_project_root(candidate):
                return candidate
    raise RuntimeError(
        "Could not locate the figures-from-scratch-test project root from "
        f"{Path(__file__).resolve()} or {Path.cwd().resolve()}"
    )


PROJECT_ROOT = _find_project_root()


def project_path(*parts: str | Path) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def configure_credentials(
    config: dict | None = None, *, credentials_path: Path | str | None = None
) -> None:
    """Load private credentials into the environment, never the job config."""
    keys = ("maap_token", "earthdata_username", "earthdata_password")
    if config is not None:
        public_values = [config.pop(key, None) for key in keys]
        if any(public_values):
            raise ValueError("Move credentials from workflow config to config/credentials.yaml")

    path = (
        Path(credentials_path)
        if credentials_path is not None
        else project_path("config", "credentials.yaml")
    )
    try:
        credentials = yaml.safe_load(path.read_text()) if path.exists() else {}
        if credentials is None:
            credentials = {}
    except yaml.YAMLError:
        raise ValueError("Invalid YAML in private credential file") from None
    if not isinstance(credentials, dict) or set(credentials) - set(keys):
        raise ValueError("Private credential file must contain only maap_token and Earthdata fields")
    if any(value is not None and not isinstance(value, str) for value in credentials.values()):
        raise ValueError("Private credential values must be strings")

    token = credentials.get("maap_token") or ""
    user = os.environ.get("EARTHDATA_USERNAME") or ""
    password = os.environ.get("EARTHDATA_PASSWORD") or ""
    if not user and not password:
        user = credentials.get("earthdata_username") or ""
        password = credentials.get("earthdata_password") or ""
    if bool(user) != bool(password):
        raise ValueError("Earthdata username and password must both be configured in the same source")

    if token and not os.environ.get(_MAAP_TOKEN_ENV):
        os.environ[_MAAP_TOKEN_ENV] = token
    if user and password:
        os.environ["EARTHDATA_USERNAME"] = user
        os.environ["EARTHDATA_PASSWORD"] = password


def configure_cryoswath_resource_paths() -> None:
    resource_root = project_path("resources")
    auxiliary_root = resource_root / "auxiliary"
    cryoswath_misc.data_path = str(resource_root)
    cryoswath_misc.l1b_path = str(resource_root / "l1b_cache")
    cryoswath_misc.l2_swath_path = str(resource_root / "l2_swath")
    cryoswath_misc.l2_poca_path = str(resource_root / "l2_poca")
    cryoswath_misc.l3_path = str(resource_root / "monthly_dataset")
    cryoswath_misc.l4_path = str(resource_root / "trends_dataset")
    cryoswath_misc.tmp_path = str(resource_root / "tmp")
    cryoswath_misc.aux_path = auxiliary_root
    cryoswath_misc.rgi_path = str(auxiliary_root / "RGI")
    cryoswath_misc.dem_path = auxiliary_root / "DEM"
    cryoswath_misc.cs_ground_tracks_path = str(
        auxiliary_root / "CryoSat-2_SARIn_ground_tracks.feather"
    )


configure_cryoswath_resource_paths()


def _nonempty_env_pair(user_key: str, password_key: str) -> EsaCredentialStatus:
    user = (os.environ.get(user_key) or "").strip()
    password = (os.environ.get(password_key) or "").strip()
    if user and password:
        return EsaCredentialStatus(
            True, f"environment variables {user_key}/{password_key}"
        )
    if user or password:
        return EsaCredentialStatus(
            False,
            notes=(f"partial environment source {user_key}/{password_key}",),
        )
    return EsaCredentialStatus(False)


def _keyring_esa_credential_status(
    env_user: str | None,
    timeout_seconds: float,
) -> EsaCredentialStatus:
    try:
        import keyring
    except ImportError:
        return EsaCredentialStatus(False)

    result: dict[str, Any] = {}

    def check_keyring():
        try:
            if keyring.get_password("iam.maap.eo.esa.int", "offline-token"):
                result["source"] = "MAAP token in keyring"
                return
            explicit_users = [env_user] if env_user else []
            for service in _ESA_KEYRING_SERVICE_CANDIDATES:
                for user in explicit_users:
                    if keyring.get_password(service, user):
                        result["source"] = f"keyring service {service}"
                        return
                for username_key in _ESA_KEYRING_DEFAULT_USER_KEYS:
                    keyring_user = keyring.get_password(service, username_key)
                    if keyring_user and keyring.get_password(service, keyring_user):
                        result["source"] = f"keyring service {service}"
                        return
        except Exception:  # noqa: BLE001
            result["note"] = "keyring unavailable"

    thread = threading.Thread(target=check_keyring, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        return EsaCredentialStatus(
            False,
            notes=(f"keyring check timed out after {timeout_seconds:g} s",),
        )
    if "source" in result:
        return EsaCredentialStatus(True, result["source"])
    if "note" in result:
        return EsaCredentialStatus(False, notes=(result["note"],))
    return EsaCredentialStatus(False)


def _netrc_esa_credential_status(netrc_path: Path) -> EsaCredentialStatus:
    netrc_path = netrc_path.expanduser()
    if not netrc_path.exists():
        return EsaCredentialStatus(False)
    if not os.access(netrc_path, os.R_OK):
        return EsaCredentialStatus(
            False,
            notes=(f"netrc file is not readable: {netrc_path}",),
        )
    try:
        parsed = netrc_mod.netrc(str(netrc_path))
    except Exception as err:  # noqa: BLE001
        return EsaCredentialStatus(
            False,
            notes=(f"netrc file cannot be parsed: {err}",),
        )
    auth = parsed.authenticators(_ESA_CS2_HOST)
    if auth is None:
        return EsaCredentialStatus(
            False,
            notes=(f"netrc missing machine {_ESA_CS2_HOST}",),
        )
    login, _, password = auth
    if login and password:
        return EsaCredentialStatus(True, f"netrc file {netrc_path}")
    return EsaCredentialStatus(
        False,
        notes=(f"netrc machine {_ESA_CS2_HOST} is missing login or password",),
    )


def _legacy_config_esa_credential_status(config_path: Path) -> EsaCredentialStatus:
    config_path = config_path.expanduser()
    if not config_path.exists():
        return EsaCredentialStatus(False)
    config = ConfigParser()
    config.read(config_path)
    if "user" not in config:
        return EsaCredentialStatus(False)
    user = (config["user"].get("name") or "").strip()
    password = (config["user"].get("password") or "").strip()
    if user and password:
        return EsaCredentialStatus(True, f"legacy config {config_path} [user]")
    if user or password:
        return EsaCredentialStatus(
            False,
            notes=(f"partial legacy config source {config_path} [user]",),
        )
    return EsaCredentialStatus(False)


def resolve_esa_credential_status(
    *,
    home: Path | str | None = None,
    config_path: Path | str | None = None,
    check_keyring: bool = True,
    keyring_timeout_seconds: float = 2.0,
) -> EsaCredentialStatus:
    """Return whether an ESA CryoSat-2 credential source is configured.

    This is intentionally an availability check only. It does not authenticate
    over the network or print secret values.
    """
    notes: list[str] = []
    if os.environ.get(_MAAP_TOKEN_ENV):
        return EsaCredentialStatus(True, f"environment variable {_MAAP_TOKEN_ENV}")
    env_status = _nonempty_env_pair(_ESA_ENV_USER, _ESA_ENV_PASSWORD)
    if env_status.available:
        return env_status
    notes.extend(env_status.notes)

    if check_keyring:
        keyring_status = _keyring_esa_credential_status(
            env_user=(os.environ.get(_ESA_ENV_USER) or "").strip() or None,
            timeout_seconds=keyring_timeout_seconds,
        )
        if keyring_status.available:
            return keyring_status
        notes.extend(keyring_status.notes)

    home_path = Path.home() if home is None else Path(home)
    netrc_status = _netrc_esa_credential_status(home_path / ".netrc")
    if netrc_status.available:
        return netrc_status
    notes.extend(netrc_status.notes)

    cfg_status = _legacy_config_esa_credential_status(
        PROJECT_ROOT / "config.ini" if config_path is None else Path(config_path)
    )
    if cfg_status.available:
        return cfg_status
    notes.extend(cfg_status.notes)

    return EsaCredentialStatus(False, notes=tuple(notes))


def _local_l1b_track_available(track_id: str | pd.Timestamp) -> bool:
    track_timestamp = pd.Timestamp(track_id)
    track_id_str = track_timestamp.strftime("%Y%m%dT%H%M%S")
    track_dir = Path(cryoswath_misc.l1b_path) / track_timestamp.strftime("%Y/%m")
    if not track_dir.is_dir():
        return False
    for candidate in track_dir.iterdir():
        if (
            candidate.is_file()
            and candidate.name.endswith(".nc")
            and fnmatch.fnmatch(candidate.name, "*CS_????_SIR_SIN_1B_*")
            and candidate.name[19:34] == track_id_str
        ):
            return True
    return False


def missing_local_l1b_track_ids(track_ids: list[str | pd.Timestamp]) -> list[str]:
    return [
        pd.Timestamp(track_id).strftime("%Y%m%dT%H%M%S")
        for track_id in track_ids
        if not _local_l1b_track_available(track_id)
    ]


def warn_if_esa_credentials_missing_for_l1b(
    track_ids: list[str | pd.Timestamp],
    *,
    home: Path | str | None = None,
    config_path: Path | str | None = None,
    check_keyring: bool = True,
) -> bool:
    """Warn when missing local L1b inputs are likely to require ESA auth.

    Credential sources are not inspected when all requested tracks are already
    present locally.
    """
    missing_track_ids = missing_local_l1b_track_ids(track_ids)
    if not missing_track_ids:
        return False
    credential_status = resolve_esa_credential_status(
        home=home,
        config_path=config_path,
        check_keyring=check_keyring,
    )
    if credential_status.available:
        return False
    note = ""
    if credential_status.notes:
        note = " Notes: " + "; ".join(credential_status.notes) + "."
    warnings.warn(
        "ESA CryoSat-2 credentials were not found, and local L1b files are "
        "missing for track(s) "
        f"{', '.join(missing_track_ids)}. The workflow will continue, but "
        "cryoswath may try to download these files and can fail or appear to "
        "stall without authentication. Configure maap_token in config/credentials.yaml, "
        "ESA_MAAP_OFFLINE_TOKEN, or cryoswath update-maap-token for MAAP delivery. "
        "EOIAM_USER/EOIAM_PASSWORD, keyring, "
        f"$HOME/.netrc with machine {_ESA_CS2_HOST}, or legacy config.ini "
        "[user] credentials support Science Server FTP fallback."
        f"{note}",
        UserWarning,
        stacklevel=2,
    )
    return True


def _maybe_project_path(value: Path | str | Any) -> Path | str | Any:
    if isinstance(value, (str, Path)):
        value_path = Path(value)
        if not value_path.is_absolute() and (
            "/" in str(value_path)
            or str(value_path).startswith(("resources/", "results/", "logs/", "paper/"))
        ):
            return project_path(value_path)
    return value


o1o2reg_tuple_list = [
    (1, [2, 4, 5, 6]),
    (3, list(range(1, 7 + 1))),
    (4, list(range(1, 8 + 1))),
    (5, list(range(11, 5 + 11))),
    (6, [1]),
    (7, [1]),
    (8, [1, 2, 3]),
    (9, [1, 2, 3]),
]

rgi_names = {
    1: {
        "name": "Alaska",
        "long_code": "01_alaska",
        2: "Alaska Range (Wrangell/Kilbuck)",
        4: "West Chugach Mountains (Talkeetna)",
        5: "Saint Elias Mountains",
        6: "North Coast Ranges",
    },
    3: {
        "name": "Arctic Canada North",
        "long_code": "03_arctic_canada_north",
        1: "North Ellesmere Island",
        2: "Axel Heiberg and Meighen Is",
        3: "North Central Ellesmere Island",
        4: "South Central Ellesmere Island",
        5: "South Ellesmere Island (Northwest Devon)",
        6: "Devon Island",
        7: "Melville Island",
    },
    4: {
        "name": "Arctic Canada South",
        "long_code": "04_arctic_canada_south",
        1: "Bylot Island",
        2: "West Baffin Island",
        3: "North Baffin Island",
        4: "Northeast Baffin Island",
        5: "East Central Baffin Island",
        6: "South East Baffin Island",
        7: "Cumberland Sound",
        8: "Frobisher Bay",
    },
    5: {
        "name": "Greenland Periphery",
        "long_code": "05_greenland_periphery",
        11: "North Greenland",
        12: "West Greenland",
        13: "South West Greenland",
        14: "South East Greenland",
        15: "East Greenland",
    },
    6: {"name": "Iceland", "long_code": "06_iceland", 1: "Iceland"},
    7: {
        "name": "Svalbard and Jan Mayen",
        "long_code": "07_svalbard_jan_mayen",
        1: "Svalbard",
    },
    8: {
        "name": "Scandinavia",
        "long_code": "08_scandinavia",
        1: "North Scandinavia",
        2: "Southwest Scandinavia",
        3: "Southeast Scandinavia",
    },
    9: {
        "name": "Russian Arctic",
        "long_code": "09_russian_arctic",
        1: "Franz Josef Land",
        2: "Novaya Zemlya",
        3: "Severnaya Zemlya",
    },
}


def download_file(url: str, dest: Path, *, verify: bool = True):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120, verify=verify) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", "0"))
        _iter = r.iter_content(chunk_size=8192)
        if total > 0:
            _iter = tqdm(_iter, desc=dest.stem, total=total, leave=False)
        else:
            print(f"\rloading {dest.stem} ... ", end="")
        try:
            with open(dest, "wb") as f:
                for chunk in _iter:
                    f.write(chunk)
        except:
            dest.unlink(missing_ok=True)
            raise
    print(f"\r✔️ {dest}")


def make_o2reg_filename_token_list(out_file: Path):
    from cryoswath.misc import rgi_code_translator

    with open(out_file, "w") as f:
        for o1, o2_list in o1o2reg_tuple_list:
            for o2 in o2_list:
                print(
                    "__".join(
                        [strip_spec_chars(rgi_code_translator(f"{o1:02d}"))]
                        + (
                            [
                                strip_spec_chars(
                                    rgi_code_translator(f"{o1:02d}-{o2:02d}")
                                )
                            ]
                            if o2 != "all"
                            else []
                        )
                    ),
                    file=f,
                )


def strip_spec_chars(chrstr: str) -> str:
    return (
        chrstr.replace(" (", "-").replace(")", "").replace("/", "-").replace(" ", "_")
    )


def snakemake_out0_or_fallback(fallback: Path | str) -> Path:
    if "snakemake" in globals():
        return Path(globals()["snakemake"].output[0])
    return Path(_maybe_project_path(fallback))


def snakemake_fallback_builder(_globals) -> Callable:
    def snakemake_fallback(
        _var: Literal["input", "output", "param"], key: str | int, fallback: Any
    ) -> Any:
        if "snakemake" in _globals:
            return getattr(_globals["snakemake"], _var)[key]
        return _maybe_project_path(fallback)

    return snakemake_fallback


@contextmanager
def out_to_snakemake_log_or_fallback_stdout(snakemake, delete_old: bool = False):
    if snakemake:
        with open(snakemake.log[0], "w" if delete_old else "a") as lf:
            orig_pipes = (sys.stdout, sys.stderr)
            sys.stdout = lf
            sys.stderr = lf
            try:
                yield
            finally:
                sys.stdout, sys.stderr = orig_pipes
    else:
        yield


def rgi_uncertainty(rgi_id: int | tuple[int, int]) -> np.floating:
    return (
        3
        * 0.039
        * load_glacier_outlines(
            f"0{rgi_id}"
            if isinstance(rgi_id, int)
            else f"{rgi_id[0]:02d}-{rgi_id[1]:02d}",
            "glaciers",
            union=False,
        ).area_km2  # pyright: ignore[reportAttributeAccessIssue]
        ** 0.70
    ).sum()


def fit_deseasoned_trend(ts):
    return sm.OLS(
        ts,
        pd.concat(
            [
                TimeTrend(True, 1).in_sample(ts.index),
                CalendarFourier("YE", 2).in_sample(ts.index),
            ],
            axis=1,
        ),
    ).fit()


def to_yaml(_dict, path):
    yaml.safe_dump(
        _dict,
        open(path, "w"),
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        width=88,
    )


def precision(val):
    return max(0, round(1 - np.log10(val)))


def add_result(
    _dict: dict,
    basename: str,
    val: float,
    unc: float | None = None,
    units: list[str] = [],
):
    _dict[basename] = {"value": float(val)}
    if unc:
        _dict[basename].update(uncertainty=float(unc))
    if units:
        _dict[basename].update(units=units)


def get_interp_unc(path: Path | str) -> xr.DataArray:
    return (
        pd.read_csv(
            path,
            index_col="elev_diff_interp_flag",
        )
        .to_xarray()
        .to_dataarray("dummy")
        .isel(dummy=0)
        .drop_vars("dummy")
    )


def get_interp_unc_corr(path: Path | str) -> xr.DataArray:
    interp_unc_corr = pd.read_csv(
        path,
        index_col="elev_diff_interp_flag",
    ).rename_axis("cov_i")
    return (
        interp_unc_corr.rename(columns={x: int(x) for x in interp_unc_corr.columns})
        .to_xarray()
        .to_dataarray("cov_j")
    )


def calculate_mean_elevation_and_uncertainty(
    ds: xr.Dataset,
    interp_unc: xr.DataArray,
    interp_unc_corr: xr.DataArray,
) -> xr.Dataset:
    spatial_mean = ds.elev_diff.mean(["x", "y"]).persist()
    decmp_res = seasonal_decompose(spatial_mean, period=12, extrapolate_trend=True)
    sq_unc_observed_cells = (
        ds.elev_diff_error.where(ds.elev_diff_interp_flag == 0)
        .coarsen(x=4, y=4, boundary="pad")
        .sum()
        ** 2
    ).sum(["x", "y"])
    unc_by_interp = (
        ds.groupby(["time", "elev_diff_interp_flag"]).map(
            lambda ds: ds.elev_diff_interp_flag.count()
        )
        * interp_unc
    )
    sq_unc_interpolated_cells = (
        unc_by_interp.rename(elev_diff_interp_flag="cov_i")
        * interp_unc_corr
        * unc_by_interp.rename(elev_diff_interp_flag="cov_j")
    ).sum(["cov_i", "cov_j"])
    unc_total_2sigma = (
        (sq_unc_observed_cells + sq_unc_interpolated_cells) ** 0.5
        / ds.elev_diff.notnull().any("time").sum()
        * 2
    )
    out = xr.Dataset(
        {
            "elevation": (spatial_mean - decmp_res.trend[0]),
            "uncertainty": unc_total_2sigma,
        }
    )
    out = out.drop_vars([_var for _var in ds.coords if _var == "spatial_ref"])
    return out
