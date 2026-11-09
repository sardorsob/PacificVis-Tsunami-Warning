"""Only re-render trusted closed-G2 diagnostic artists for deterministic checking."""
import hashlib
import importlib.util
import json
from pathlib import Path

import xarray as xr
from analysis.arrival.model_sensitivity_priors import _population_spec

root=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
helper=Path('/private/tmp/check-ms6-recovery-science.py')
assert hashlib.sha256(helper.read_bytes()).hexdigest()=='7bda5269951809400825c8262ea0bb7434127c85d7a322295719f0dcfcd54713'
proof=Path('/private/tmp/tsunami-G2-closed-WORKER-diagnostic-process-proof.json')
assert hashlib.sha256(proof.read_bytes()).hexdigest()=='180df32f94dd48dd201f5846b9e702c26147143b05c518cb3697e9d3df2f0e83'
case=json.loads(proof.read_text());assert case['closed'] and case['job_id']=='full-smoke-1-a'
raw=root/'data/processed/models/arrival-development-recovery-v1/full-smoke-1-a.nc'
assert hashlib.sha256(raw.read_bytes()).hexdigest()=='0d9fcebefeb65471f9ce44e3f1d7b80479fde59711e85ed566af40a189ed9146'
assert (Path('/private/tmp/ms6-G2-closed-scientific-diagnostic')/'scientific-diagnostic.json').is_file()
spec=importlib.util.spec_from_file_location('G_plot_arithmetic',helper)
assert spec and spec.loader
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
out=Path('/private/tmp/ms6-G2-chartcheck-render');out.mkdir(exist_ok=True)
with xr.open_dataset(raw,group='posterior',engine='h5netcdf') as post, xr.open_dataset(raw,group='sample_stats',engine='h5netcdf') as stats:
    q.render_diagnostics(post[list(_population_spec('T-OBS','pooled'))],stats,case['job'],out)
