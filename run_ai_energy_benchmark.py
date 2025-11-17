#!/usr/bin/env python3
"""
Wrapper script to run ai_energy_benchmarks with optimum-benchmark compatible configs.
Converts optimum-benchmark Hydra config to ai_energy_benchmarks format.
"""

import sys
import json
from pathlib import Path
from omegaconf import OmegaConf
import logging
from reasoning_helpers import get_token_parameters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_hydra_args(args):
    """Parse Hydra-style arguments (key=value format)"""
    overrides = {}
    config_name = None

    for arg in args:
        if arg.startswith("--config-name"):
            if "=" in arg:
                config_name = arg.split("=", 1)[1]
            else:
                # Next arg is the config name
                idx = args.index(arg)
                if idx + 1 < len(args):
                    config_name = args[idx + 1]
        elif "=" in arg and not arg.startswith("--"):
            key, value = arg.split("=", 1)
            overrides[key] = value

    return config_name, overrides


def load_optimum_config(config_name, config_dir="/optimum-benchmark/energy_star"):
    """Load optimum-benchmark configuration"""
    # Try multiple locations
    search_paths = [
        Path(config_dir) / f"{config_name}.yaml",
        Path(config_dir) / config_name,
        # Also try in current directory (for AIEnergyScore configs)
        Path(f"{config_name}.yaml"),
        Path(config_name),
    ]

    for config_path in search_paths:
        if config_path.exists():
            logger.info(f"Loading config from: {config_path}")
            return OmegaConf.load(config_path)

    raise FileNotFoundError(
        f"Config not found in any of: {[str(p) for p in search_paths]}"
    )


def get_available_gpu_count():
    """Get the number of available GPUs"""
    try:
        import torch

        return torch.cuda.device_count()
    except Exception:
        return 0


def check_dataset_size(dataset_name, num_samples_requested):
    """Check if dataset has enough samples and warn if not.

    Args:
        dataset_name: Name of the dataset
        num_samples_requested: Number of samples requested

    Returns:
        Actual number of samples that will be used
    """
    try:
        from datasets import load_dataset

        logger.info(f"Checking dataset size for: {dataset_name}")

        # Load dataset to check size
        dataset = load_dataset(dataset_name, split="train")
        dataset_size = len(dataset)

        logger.info(f"Dataset '{dataset_name}' contains {dataset_size} samples")

        if num_samples_requested > dataset_size:
            logger.warning("=" * 80)
            logger.warning(
                f"WARNING: Requested {num_samples_requested} prompts, but dataset only has {dataset_size} samples!"
            )
            logger.warning(f"Only {dataset_size} prompts will be processed.")
            logger.warning("=" * 80)
            return dataset_size

        return num_samples_requested

    except Exception as e:
        logger.warning(f"Could not check dataset size: {e}")
        logger.warning("Proceeding with requested number of samples...")
        return num_samples_requested


def convert_to_ai_energy_benchmarks_config(optimum_config, overrides):
    """Convert optimum-benchmark config to ai_energy_benchmarks format"""

    # Apply overrides to optimum config
    for key, value in overrides.items():
        OmegaConf.update(optimum_config, key, value, merge=True)

    # Extract backend config
    backend = optimum_config.get("backend", {})
    scenario = optimum_config.get("scenario", {})

    # Get device_ids and ensure they're integers
    device_ids = backend.get("device_ids", [0])
    if isinstance(device_ids, str):
        # Handle comma-separated string like "0, 1, 2, 3"
        device_ids = [int(d.strip()) for d in device_ids.split(",")]
    elif isinstance(device_ids, (list, tuple)):
        device_ids = [int(d) for d in device_ids]
    else:
        device_ids = [int(device_ids)]

    # Validate and adjust device_ids based on available GPUs
    available_gpus = get_available_gpu_count()
    if available_gpus > 0:
        # Filter out device IDs that exceed available GPUs
        valid_device_ids = [d for d in device_ids if d < available_gpus]
        if not valid_device_ids:
            # If no valid IDs, use first GPU
            valid_device_ids = [0]
        if valid_device_ids != device_ids:
            logger.warning(
                f"Adjusted device_ids from {device_ids} to {valid_device_ids} (found {available_gpus} GPUs)"
            )
            device_ids = valid_device_ids
    else:
        logger.warning("No GPUs detected, using device_ids=[0] anyway")
        device_ids = [0]

    # Build ai_energy_benchmarks compatible config
    # Get reasoning-aware token parameters
    reasoning_params = scenario.get("reasoning_params", None)
    token_params = get_token_parameters(reasoning_params)

    config = {
        "backend": {
            "type": "pytorch",
            "model": backend.get("model", ""),
            "device": backend.get("device", "cuda"),
            "device_ids": device_ids,
            "torch_dtype": backend.get("torch_dtype", "auto"),
            "device_map": backend.get("device_map", "auto"),
        },
        "dataset": {
            "name": scenario.get("dataset_name", "EnergyStarAI/text_generation"),
            "text_column": scenario.get("text_column_name", "text"),
            "num_samples": int(scenario.get("num_samples", 1000)),
        },
        "generation": {
            "max_new_tokens": int(
                scenario.get("generate_kwargs", {}).get(
                    "max_new_tokens", token_params["max_new_tokens"]
                )
            ),
            "min_new_tokens": int(
                scenario.get("generate_kwargs", {}).get(
                    "min_new_tokens", token_params["min_new_tokens"]
                )
            ),
        },
        "reasoning": {
            "enabled": scenario.get("reasoning", False),
            "params": reasoning_params,
        },
        "metrics": {
            "enabled": True,
            "project_name": "ai_energy_benchmark",
        },
    }

    return config


def run_pytorch_backend(config, output_dir):
    """Run ai_energy_benchmarks with PyTorch backend"""
    try:
        from ai_energy_benchmarks.config.parser import (
            BenchmarkConfig,
            BackendConfig,
            ScenarioConfig,
            MetricsConfig,
            ReporterConfig,
        )
        from ai_energy_benchmarks.runner import BenchmarkRunner

        logger.info("Initializing ai_energy_benchmarks PyTorch backend")
        logger.info(f"Model: {config['backend']['model']}")
        logger.info(f"Dataset: {config['dataset']['name']}")
        logger.info(f"Samples: {config['dataset']['num_samples']}")

        # Check dataset size and warn if requested samples exceed dataset size
        actual_num_samples = check_dataset_size(
            config["dataset"]["name"], config["dataset"]["num_samples"]
        )
        # Update config with actual number of samples that will be used
        config["dataset"]["num_samples"] = actual_num_samples

        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Build BenchmarkConfig using dataclasses
        backend_cfg = BackendConfig(
            type="pytorch",
            model=config["backend"]["model"],
            device=config["backend"]["device"],
            device_ids=config["backend"]["device_ids"],
        )

        scenario_cfg = ScenarioConfig(
            dataset_name=config["dataset"]["name"],
            text_column_name=config["dataset"]["text_column"],
            num_samples=config["dataset"]["num_samples"],
            reasoning=config["reasoning"]["enabled"],
            reasoning_params=config["reasoning"]["params"],
            generate_kwargs=config["generation"],
        )

        metrics_cfg = MetricsConfig(
            enabled=True,
            type="codecarbon",
            project_name=config["metrics"]["project_name"],
            output_dir=str(output_path / "emissions"),
            country_iso_code="USA",
            region="california",
        )

        reporter_cfg = ReporterConfig(
            type="csv",
            output_file=str(output_path / "benchmark_results.csv"),
        )

        bench_config = BenchmarkConfig(
            name="ai_energy_benchmark",
            backend=backend_cfg,
            scenario=scenario_cfg,
            metrics=metrics_cfg,
            reporter=reporter_cfg,
            output_dir=str(output_path),
        )

        # Create runner
        runner = BenchmarkRunner(bench_config)

        # Validate
        if not runner.validate():
            logger.error("Benchmark validation failed")
            sys.exit(1)

        # Run benchmark
        logger.info("Starting benchmark...")
        results = runner.run()

        # Save results as JSON for compatibility
        result_file = output_path / "benchmark_report.json"
        with open(result_file, "w") as f:
            json.dump(results, f, indent=2)

        logger.info("Benchmark completed successfully")
        logger.info(f"Results saved to: {result_file}")

        if "energy" in results:
            logger.info(
                f"GPU Energy: {results['energy'].get('gpu_energy_wh', 0):.2f} Wh"
            )

        return results

    except ImportError as e:
        logger.error(f"ai_energy_benchmarks not installed or missing dependencies: {e}")
        logger.error("Install with: pip install ai_energy_benchmarks[pytorch]")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error running benchmark: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


def run_vllm_backend(config, output_dir, endpoint):
    """Run ai_energy_benchmarks with vLLM backend"""
    try:
        from ai_energy_benchmarks.config.parser import (
            BenchmarkConfig,
            BackendConfig,
            ScenarioConfig,
            MetricsConfig,
            ReporterConfig,
        )
        from ai_energy_benchmarks.runner import BenchmarkRunner

        logger.info("Initializing ai_energy_benchmarks vLLM backend")
        logger.info(f"Endpoint: {endpoint}")
        logger.info(f"Model: {config['backend']['model']}")
        logger.info(f"Dataset: {config['dataset']['name']}")
        logger.info(f"Samples: {config['dataset']['num_samples']}")

        # Check dataset size and warn if requested samples exceed dataset size
        actual_num_samples = check_dataset_size(
            config["dataset"]["name"], config["dataset"]["num_samples"]
        )
        # Update config with actual number of samples that will be used
        config["dataset"]["num_samples"] = actual_num_samples

        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Build BenchmarkConfig using dataclasses
        backend_cfg = BackendConfig(
            type="vllm",
            model=config["backend"]["model"],
            endpoint=endpoint,
        )

        scenario_cfg = ScenarioConfig(
            dataset_name=config["dataset"]["name"],
            text_column_name=config["dataset"]["text_column"],
            num_samples=config["dataset"]["num_samples"],
            reasoning=config["reasoning"]["enabled"],
            reasoning_params=config["reasoning"]["params"],
            generate_kwargs=config["generation"],
        )

        metrics_cfg = MetricsConfig(
            enabled=True,
            type="codecarbon",
            project_name=config["metrics"]["project_name"],
            output_dir=str(output_path / "emissions"),
            country_iso_code="USA",
            region="california",
        )

        reporter_cfg = ReporterConfig(
            type="csv",
            output_file=str(output_path / "benchmark_results.csv"),
        )

        bench_config = BenchmarkConfig(
            name="ai_energy_benchmark_vllm",
            backend=backend_cfg,
            scenario=scenario_cfg,
            metrics=metrics_cfg,
            reporter=reporter_cfg,
            output_dir=str(output_path),
        )

        # Create runner
        runner = BenchmarkRunner(bench_config)

        # Validate
        if not runner.validate():
            logger.error("Benchmark validation failed")
            sys.exit(1)

        # Run benchmark
        logger.info("Starting benchmark...")
        results = runner.run()

        # Save results as JSON for compatibility
        result_file = output_path / "benchmark_report.json"
        with open(result_file, "w") as f:
            json.dump(results, f, indent=2)

        logger.info("Benchmark completed successfully")
        logger.info(f"Results saved to: {result_file}")

        if "energy" in results:
            logger.info(
                f"GPU Energy: {results['energy'].get('gpu_energy_wh', 0):.2f} Wh"
            )

        return results

    except ImportError as e:
        logger.error(f"ai_energy_benchmarks not installed: {e}")
        logger.error("Install with: pip install ai_energy_benchmarks")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error running benchmark: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


def main():
    import os

    # Parse arguments
    args = sys.argv[1:]
    config_name, overrides = parse_hydra_args(args)

    if not config_name:
        logger.error("No config name provided. Use --config-name <name>")
        sys.exit(1)

    # Get environment variables
    output_dir = os.getenv("RESULTS_DIR", "/results")
    backend_type = os.getenv("BENCHMARK_BACKEND", "pytorch")
    vllm_endpoint = os.getenv("VLLM_ENDPOINT", "")

    # Load and convert config
    logger.info(f"Loading optimum-benchmark config: {config_name}")
    optimum_config = load_optimum_config(config_name)

    logger.info("Converting to ai_energy_benchmarks format")
    config = convert_to_ai_energy_benchmarks_config(optimum_config, overrides)

    # Run appropriate backend
    if backend_type == "vllm":
        if not vllm_endpoint:
            logger.error("VLLM_ENDPOINT environment variable required for vLLM backend")
            sys.exit(1)
        _ = run_vllm_backend(config, output_dir, vllm_endpoint)
    else:
        _ = run_pytorch_backend(config, output_dir)

    logger.info(f"Results saved to: {output_dir}/benchmark_report.json")


if __name__ == "__main__":
    main()
