"""Prepare trusted, file-backed recipes with bounded integer parameters."""

import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from .client import describe, prepare_manifest
from .worker import canonical, checked_path, read_file


VERSION = "polisplexity.hpc.recipe.v1"
KEYS = ("recipe", "description", "profile", "parameters")


def load(root, recipe):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", recipe):
        raise ValueError("Use an approved recipe ID")
    directory = Path("recipes") / recipe
    spec = json.loads(read_file(root, (directory / "recipe.json").as_posix()))
    if spec["version"] != VERSION or spec["recipe"] != recipe or spec["profile"] != "slurm":
        raise ValueError(f"Invalid recipe descriptor: {recipe}")
    return directory, spec


def list_recipes(root):
    recipes = []
    for path in sorted((root / "recipes").glob("*/recipe.json")):
        _, spec = load(root, path.parent.name)
        recipes.append({**{key: spec[key] for key in KEYS}, "resources": spec["job"]["resources"]})
    return recipes


def prepare_recipe(root, recipe, parameters):
    directory, spec = load(root, recipe)
    limits = spec["parameters"]
    if parameters.keys() != limits.keys():
        raise ValueError("Expected parameters: " + ", ".join(sorted(limits)))
    for name, value in parameters.items():
        bounds = limits[name]
        if type(value) is not int or not bounds["minimum"] <= value <= bounds["maximum"]:
            raise ValueError(f"{name} must be an integer between {bounds['minimum']} and {bounds['maximum']}")
    template = spec["job"]
    manifest = {**template, "argv": [
        arg if isinstance(arg, str) else str(parameters[arg["parameter"]])
        for arg in template["argv"]
    ]}
    prepared = describe(prepare_manifest(root / directory, manifest, spec["profile"]))
    path = checked_path((directory / prepared["manifest_sha256"]).as_posix())
    with NamedTemporaryFile(dir=root / directory, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(canonical(manifest))
            stream.close()
            os.replace(temporary, root / path)
        finally:
            temporary.unlink(missing_ok=True)
    return {**prepared, "recipe": recipe, "parameters": parameters, "manifest": path.as_posix()}
