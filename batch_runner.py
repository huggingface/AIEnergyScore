#!/usr/bin/env python3
"""
AI Energy Score Batch Runner

Runs benchmarks for multiple models from a CSV configuration file,
with support for model-specific parameters, filtering, and comprehensive
results tracking.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

from reasoning_helpers import is_reasoning_enabled, get_token_parameters

# Configure PyTorch CUDA allocator to reduce fragmentation
# This must be set BEFORE any CUDA operations
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "ai_energy_benchmarks"))

from debug_logger import DebugLogger
from model_config_parser import ModelConfig, ModelConfigParser
from parameter_handler import ParameterHandler
from results_aggregator import ResultsAggregator

# Import ai_energy_benchmarks components (only needed for vLLM)
try:
    from ai_energy_benchmarks.config.parser import (
        BackendConfig,
        BenchmarkConfig,
        MetricsConfig,
        ReporterConfig,
        ScenarioConfig,
    )
    from ai_energy_benchmarks.runner import BenchmarkRunner
except ImportError as e:
    print(f"Warning: ai_energy_benchmarks not installed or not in path: {e}")
    print(
        "PyTorch backend will use docker, vLLM backend requires: pip install ai_energy_benchmarks"
    )
    # Set all to None for type hints (won't be used with PyTorch backend)
    BackendConfig = None  # type: ignore
    BenchmarkConfig = None  # type: ignore
    MetricsConfig = None  # type: ignore
    ReporterConfig = None  # type: ignore
    ScenarioConfig = None  # type: ignore
    BenchmarkRunner = None  # type: ignore


class BatchRunner:
    """Batch runner for AI Energy Score benchmarks."""

    def __init__(
        self,
        csv_path: str,
        output_dir: str,
        backend_type: str = "pytorch",
        endpoint: str = "http://localhost:8000/v1",
        prompts_file: Optional[str] = None,
        num_prompts: Optional[int] = None,
    ):
        """Initialize batch runner.

        Args:
            csv_path: Path to models CSV file
            output_dir: Output directory for results
            backend_type: Backend type (default: pytorch, also supports vllm)
            endpoint: vLLM endpoint URL (for vllm backend)
            prompts_file: Path to prompts file (optional)
            num_prompts: Number of prompts to run (optional, defaults to all)
        """
        self.csv_path = csv_path
        self.output_dir = Path(output_dir)
        self.backend_type = backend_type
        self.endpoint = endpoint
        self.num_prompts = num_prompts

        # Setup directories
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir = self.output_dir / "logs"
        self.logs_dir.mkdir(exist_ok=True)
        self.runs_dir = self.output_dir / "individual_runs"
        self.runs_dir.mkdir(exist_ok=True)

        # Initialize results aggregator
        self.aggregator = ResultsAggregator(
            output_file=str(self.output_dir / "master_results.csv")
        )

        # Setup prompts
        if prompts_file:
            self.prompts_file = prompts_file
        else:
            # Default to None - will use HuggingFace dataset EnergyStarAI/text_generation
            self.prompts_file = None

    def _run_via_docker(
        self, config: ModelConfig, run_dir: Path, logger: DebugLogger
    ) -> Optional[Dict]:
        """Run benchmark via docker using run_docker.sh.

        Args:
            config: ModelConfig to run
            run_dir: Output directory for this run
            logger: Logger instance

        Returns:
            Results dictionary if successful, None otherwise
        """
        try:
            # Prepare docker command
            script_dir = Path(__file__).parent
            run_docker_script = script_dir / "run_docker.sh"

            if not run_docker_script.exists():
                logger.error(f"run_docker.sh not found at: {run_docker_script}")
                return None

            # Build command - use text_generation config with overrides
            cmd = [
                str(run_docker_script),
                "-n",
                str(self.num_prompts or 10),
                "--config-name",
                "text_generation",
            ]

            # Add overrides for model and dataset
            cmd.append(f"backend.model={config.model_id}")

            # Override dataset if custom prompts file is provided
            if self.prompts_file:
                cmd.append(f"scenario.dataset_name={self.prompts_file}")
            else:
                # Use default dataset
                cmd.append("scenario.dataset_name=EnergyStarAI/text_generation")

            # Add reasoning parameters if actually enabled
            if is_reasoning_enabled(config.reasoning_params):
                cmd.append("scenario.reasoning=True")
                # Note: reasoning_params is a dict, needs special handling
                for key, value in config.reasoning_params.items():
                    # Convert boolean values to lowercase strings for Hydra/OmegaConf
                    if isinstance(value, bool):
                        value_str = str(value).lower()
                    else:
                        value_str = str(value)
                    cmd.append(f"scenario.reasoning_params.{key}={value_str}")

                # For reasoning modes: Remove token constraints to allow model to generate as needed
                # Set very high max to avoid truncation, no min to allow short responses
                cmd.append("scenario.generate_kwargs.max_new_tokens=8192")
                cmd.append("scenario.generate_kwargs.min_new_tokens=1")
            else:
                cmd.append("scenario.reasoning=False")

                # For non-reasoning modes: Fixed short response (10 tokens)
                cmd.append("scenario.generate_kwargs.max_new_tokens=10")
                cmd.append("scenario.generate_kwargs.min_new_tokens=10")

            # Set environment variables
            env = os.environ.copy()
            env["BENCHMARK_BACKEND"] = "pytorch"
            env["RESULTS_DIR"] = str(
                run_dir.resolve()
            )  # Convert to absolute path for docker
            env["DOCKER_IMAGE"] = os.getenv("DOCKER_IMAGE", "ai_energy_score")
            env["HF_HOME"] = os.getenv(
                "HF_HOME", str(Path.home() / ".cache" / "huggingface")
            )

            logger.info(f"Running docker command: {' '.join(cmd)}")
            logger.info(f"Results will be saved to: {run_dir}")

            # Run docker command
            result = subprocess.run(
                cmd,
                env=env,
                cwd=script_dir,
                capture_output=True,
                text=True,
            )

            # Log output
            if result.stdout:
                logger.debug(f"Docker stdout:\n{result.stdout}")
            if result.stderr:
                logger.debug(f"Docker stderr:\n{result.stderr}")

            if result.returncode != 0:
                logger.error(
                    f"Docker command failed with return code {result.returncode}"
                )
                logger.error(f"Stderr: {result.stderr}")
                return None

            # Parse results from benchmark_report.json
            results_file = run_dir / "benchmark_report.json"
            if not results_file.exists():
                logger.error(f"Results file not found: {results_file}")
                return None

            with open(results_file, "r") as f:
                results = json.load(f)

            logger.info("Successfully loaded results from docker run")

            # Explicit Docker cleanup - ensure containers are fully stopped
            self._cleanup_docker_containers(logger)

            return results

        except subprocess.TimeoutExpired:
            logger.error("Docker command timed out after 1 hour")
            self._cleanup_docker_containers(logger)
            return None
        except Exception as e:
            logger.error(f"Error running via docker: {e}")
            logger.log_error_details(e)
            self._cleanup_docker_containers(logger)
            return None

    def _run_non_docker(
        self, config: ModelConfig, run_dir: Path, logger: DebugLogger
    ) -> Optional[Dict]:
        """Run benchmark directly without Docker using ai_energy_benchmarks.

        Args:
            config: ModelConfig to run
            run_dir: Output directory for this run
            logger: Logger instance

        Returns:
            Results dictionary if successful, None otherwise
        """
        try:
            # Check if BenchmarkRunner is available
            if BenchmarkRunner is None:
                logger.error(
                    "BenchmarkRunner not available - install ai_energy_benchmarks"
                )
                return None

            logger.info(
                "Running benchmark directly (non-Docker) using ai_energy_benchmarks..."
            )

            # Build benchmark configuration (same as vLLM backend)
            benchmark_config = self._build_benchmark_config(config, run_dir, logger)

            # Create and run benchmark
            logger.info("Initializing benchmark runner...")
            runner = BenchmarkRunner(benchmark_config)

            # Validate
            logger.info("Validating environment...")
            try:
                if not runner.validate():
                    error_msg = "Benchmark validation failed"
                    logger.error(error_msg)

                    # Try to get more details about the failure
                    logger.debug(
                        "Attempting to initialize backend directly for detailed error..."
                    )
                    try:
                        if hasattr(runner.backend, "_initialize_model"):
                            runner.backend._initialize_model()
                    except Exception as init_error:
                        detailed_error = (
                            f"Benchmark validation failed: {str(init_error)}"
                        )
                        logger.error(f"Detailed error: {detailed_error}")
                        return None

                    return None
            except Exception as val_error:
                error_msg = f"Validation error: {str(val_error)}"
                logger.error(error_msg)
                logger.log_error_details(val_error)
                return None

            # Run benchmark
            logger.info(f"Running benchmark with {self.num_prompts} prompts...")
            results = runner.run()

            return results

        except Exception as e:
            logger.error(f"Failed to run benchmark: {e}")
            logger.log_error_details(e)
            return None

    def _parse_benchmark_results(self, run_dir: Path, logger: DebugLogger) -> Dict:
        """Parse benchmark results from output files.

        Args:
            run_dir: Directory containing results
            logger: Logger instance

        Returns:
            Results dictionary
        """
        results = {}

        # Log directory contents for debugging
        logger.debug(f"Checking for results in: {run_dir}")
        if run_dir.exists():
            files = list(run_dir.iterdir())
            logger.debug(f"Files in run_dir: {[f.name for f in files]}")

        # Look for CSV results file
        csv_files = list(run_dir.glob("*.csv"))
        if csv_files:
            latest_csv = max(csv_files, key=lambda f: f.stat().st_mtime)
            logger.debug(f"Found results CSV: {latest_csv}")

            try:
                import pandas as pd

                df = pd.read_csv(latest_csv)
                logger.debug(f"CSV has {len(df)} rows")
                results["summary"] = {
                    "successful_prompts": len(df),
                    "total_prompts": len(df),
                }

                # Add performance metrics if available
                if "latency" in df.columns:
                    results["summary"]["avg_latency"] = df["latency"].mean()
                if "tokens_per_second" in df.columns:
                    results["summary"]["avg_throughput"] = df[
                        "tokens_per_second"
                    ].mean()

            except Exception as e:
                logger.warning(f"Could not parse CSV results: {e}")
        else:
            logger.warning(f"No CSV results found in {run_dir}")
            # Return minimal results to indicate completion
            results["summary"] = {
                "successful_prompts": 0,
                "total_prompts": self.num_prompts or 0,
            }

        # Look for energy/emissions data
        emissions_dir = run_dir / "emissions"
        if emissions_dir.exists():
            emissions_files = list(emissions_dir.glob("*.csv"))
            if emissions_files:
                latest_emissions = max(emissions_files, key=lambda f: f.stat().st_mtime)
                try:
                    import pandas as pd

                    df = pd.read_csv(latest_emissions)
                    results["energy"] = {
                        "total_energy_kwh": (
                            df["energy_consumed"].sum()
                            if "energy_consumed" in df.columns
                            else 0
                        ),
                        "emissions_kg_co2": (
                            df["emissions"].sum() if "emissions" in df.columns else 0
                        ),
                    }
                except Exception as e:
                    logger.warning(f"Could not parse emissions data: {e}")

        return results

    def _cleanup_docker_containers(self, logger: DebugLogger) -> None:
        """Clean up any lingering Docker containers from benchmark runs.

        Args:
            logger: Logger instance
        """
        try:
            # Wait a moment for container to fully exit
            time.sleep(1)

            # Find and remove any exited ai_energy_score containers
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    "ancestor=ai_energy_score",
                    "--filter",
                    "status=exited",
                    "-q",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0 and result.stdout.strip():
                container_ids = result.stdout.strip().split("\n")
                logger.debug(
                    f"Found {len(container_ids)} exited containers to clean up"
                )

                for container_id in container_ids:
                    try:
                        subprocess.run(
                            ["docker", "rm", "-f", container_id],
                            capture_output=True,
                            timeout=10,
                        )
                        logger.debug(f"Removed container {container_id[:12]}")
                    except Exception as rm_err:
                        logger.warning(
                            f"Failed to remove container {container_id[:12]}: {rm_err}"
                        )

            # Small delay to let Docker fully release resources
            time.sleep(0.5)

        except Exception as e:
            logger.warning(f"Docker cleanup error (non-fatal): {e}")

    def _cleanup_gpu_memory(self, logger: DebugLogger) -> None:
        """Clean up GPU memory between model runs.

        Args:
            logger: Logger instance for debug messages
        """
        try:
            import torch

            if torch.cuda.is_available():
                logger.info("Cleaning up GPU memory...")
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                gc.collect()

                # Log memory stats
                for device_id in range(torch.cuda.device_count()):
                    allocated = torch.cuda.memory_allocated(device_id) / 1024**3
                    reserved = torch.cuda.memory_reserved(device_id) / 1024**3
                    logger.debug(
                        f"GPU {device_id} after cleanup: {allocated:.2f} GiB allocated, {reserved:.2f} GiB reserved"
                    )
        except ImportError:
            logger.debug("PyTorch not available for GPU cleanup")
        except Exception as e:
            logger.warning(f"Error during GPU cleanup: {e}")

    def run_single_model(self, config: ModelConfig) -> bool:
        """Run benchmark for a single model.

        Args:
            config: ModelConfig to run

        Returns:
            True if successful, False otherwise
        """
        # Create logger for this run
        logger = DebugLogger(
            log_dir=str(self.logs_dir),
            model_name=config.model_id,
            reasoning_state=config.reasoning_state,
        )

        # Cleanup GPU memory BEFORE loading new model (only for direct execution)
        if self.backend_type != "pytorch":
            # Create a temporary logger for the pre-run cleanup
            import logging

            temp_logger = logging.getLogger(__name__)
            temp_handler = logging.StreamHandler()
            temp_handler.setLevel(logging.INFO)
            temp_logger.addHandler(temp_handler)
            temp_logger.setLevel(logging.INFO)

            try:
                import torch

                if torch.cuda.is_available():
                    temp_logger.info("Pre-run GPU cleanup...")
                    # Force garbage collection first
                    gc.collect()

                    # Empty CUDA cache
                    torch.cuda.empty_cache()

                    # Reset the peak memory stats
                    torch.cuda.reset_peak_memory_stats()

                    # Try to reset the allocator to free reserved memory
                    # This is more aggressive and will help with large model switches
                    try:
                        for device_id in range(torch.cuda.device_count()):
                            torch.cuda.reset_accumulated_memory_stats(device_id)
                            # Only reset allocator if there's significant reserved memory
                            reserved_gb = (
                                torch.cuda.memory_reserved(device_id) / 1024**3
                            )
                            if reserved_gb > 10.0:  # More than 10 GB reserved
                                temp_logger.info(
                                    f"Resetting memory allocator for GPU {device_id} ({reserved_gb:.2f} GiB reserved)"
                                )
                                with torch.cuda.device(device_id):
                                    torch.cuda.empty_cache()
                                    # Note: reset_max_memory_allocated is deprecated, using reset_peak_memory_stats instead
                    except Exception as reset_err:
                        temp_logger.warning(f"Could not reset allocator: {reset_err}")

                    torch.cuda.synchronize()

                    # Log memory stats
                    for device_id in range(torch.cuda.device_count()):
                        allocated = torch.cuda.memory_allocated(device_id) / 1024**3
                        reserved = torch.cuda.memory_reserved(device_id) / 1024**3
                        free = (
                            torch.cuda.get_device_properties(device_id).total_memory
                            - torch.cuda.memory_reserved(device_id)
                        ) / 1024**3
                        temp_logger.info(
                            f"GPU {device_id} before loading: {allocated:.2f} GiB allocated, "
                            f"{reserved:.2f} GiB reserved, {free:.2f} GiB free"
                        )
            except Exception as e:
                temp_logger.warning(f"Error during pre-run GPU cleanup: {e}")

            temp_logger.removeHandler(temp_handler)

        runner = None
        try:
            # Validate configuration
            is_valid, error_msg = ParameterHandler.validate_config(config)
            if not is_valid:
                logger.error(f"Invalid configuration: {error_msg}")
                self.aggregator.add_failed_result(
                    config, f"Invalid config: {error_msg}"
                )
                return False

            # Log configuration
            logger.log_benchmark_start(
                model_id=config.model_id,
                num_prompts=self.num_prompts or 0,
                backend=self.backend_type,
            )

            model_info = ParameterHandler.get_model_info(config)
            logger.log_config(model_info)

            # Create model-specific output directory
            run_dir = self.runs_dir / ParameterHandler.format_model_name_for_filename(
                config.model_id, config.reasoning_state
            )
            run_dir.mkdir(exist_ok=True)

            # Run benchmark based on backend type
            start_time = time.time()

            if self.backend_type == "pytorch":
                # Check if we should use Docker or direct execution
                use_docker = os.environ.get("USE_DOCKER", "true").lower() != "false"

                if use_docker:
                    logger.info("Using docker-based execution for PyTorch backend...")
                    results = self._run_via_docker(config, run_dir, logger)
                else:
                    logger.info("Using non-docker execution for PyTorch backend...")
                    results = self._run_non_docker(config, run_dir, logger)

                if results is None:
                    error_msg = "Benchmark execution failed"
                    logger.error(error_msg)
                    self.aggregator.add_failed_result(config, error_msg)
                    return False

            else:  # vllm backend
                # Use direct runner for vLLM (remote endpoint)
                logger.info("Using direct execution for vLLM backend...")

                if BenchmarkRunner is None:
                    error_msg = (
                        "BenchmarkRunner not available - install ai_energy_benchmarks"
                    )
                    logger.error(error_msg)
                    self.aggregator.add_failed_result(config, error_msg)
                    return False

                # Build benchmark configuration
                benchmark_config = self._build_benchmark_config(config, run_dir, logger)

                # Create and run benchmark
                logger.info("Initializing benchmark runner...")
                runner = BenchmarkRunner(benchmark_config)

                # Validate
                logger.info("Validating environment...")
                try:
                    if not runner.validate():
                        error_msg = "Benchmark validation failed"
                        logger.error(error_msg)

                        # Try to get more details about the failure
                        logger.debug(
                            "Attempting to initialize backend directly for detailed error..."
                        )
                        try:
                            if hasattr(runner.backend, "_initialize_model"):
                                runner.backend._initialize_model()
                        except Exception as init_error:
                            detailed_error = (
                                f"Benchmark validation failed: {str(init_error)}"
                            )
                            logger.error(f"Detailed error: {detailed_error}")
                            self.aggregator.add_failed_result(config, detailed_error)
                            return False

                        self.aggregator.add_failed_result(config, error_msg)
                        return False
                except Exception as val_error:
                    error_msg = f"Validation error: {str(val_error)}"
                    logger.error(error_msg)
                    logger.log_error_details(val_error)
                    self.aggregator.add_failed_result(config, error_msg)
                    return False

                # Run benchmark
                logger.info("Running benchmark...")
                results = runner.run()

            duration = time.time() - start_time

            # Log results
            logger.log_results(results.get("summary", {}))
            if "energy" in results:
                logger.log_results(results["energy"])

            # Save to aggregator
            self.aggregator.add_result(config, results)

            logger.log_benchmark_end(
                success=True,
                duration=duration,
                successful_prompts=results.get("summary", {}).get(
                    "successful_prompts", 0
                ),
                total_prompts=results.get("summary", {}).get("total_prompts", 0),
            )

            return True

        except Exception as e:
            logger.error("Benchmark failed with exception")
            logger.log_error_details(e)
            self.aggregator.add_failed_result(config, str(e))
            return False

        finally:
            # Cleanup logic depends on backend type
            if self.backend_type == "pytorch":
                # Docker execution - no in-process cleanup needed
                # GPU memory is automatically freed when container exits
                logger.debug(
                    "Docker execution - container cleanup handled automatically"
                )
            else:
                # Direct execution (vLLM) - cleanup runner and GPU memory
                if runner is not None:
                    logger.debug("Explicitly cleaning up runner and model...")
                    # Try to explicitly delete model from backend
                    try:
                        if hasattr(runner, "backend") and hasattr(
                            runner.backend, "model"
                        ):
                            logger.debug("Deleting model from backend...")
                            del runner.backend.model
                            runner.backend.model = None
                        if hasattr(runner, "backend") and hasattr(
                            runner.backend, "tokenizer"
                        ):
                            logger.debug("Deleting tokenizer from backend...")
                            del runner.backend.tokenizer
                            runner.backend.tokenizer = None
                        if hasattr(runner, "backend"):
                            logger.debug("Deleting backend...")
                            del runner.backend
                    except Exception as cleanup_err:
                        logger.warning(f"Error during model cleanup: {cleanup_err}")

                    logger.debug("Deleting runner object...")
                    del runner

                # Force garbage collection before GPU cache cleanup
                gc.collect()

                # Cleanup GPU memory
                self._cleanup_gpu_memory(logger)

            # Close logger
            logger.close()

    def _build_benchmark_config(
        self, config: ModelConfig, run_dir: Path, logger: DebugLogger
    ) -> BenchmarkConfig:
        """Build BenchmarkConfig for a model.

        Args:
            config: ModelConfig
            run_dir: Output directory for this run
            logger: Logger instance

        Returns:
            BenchmarkConfig object
        """
        # Backend configuration
        if self.backend_type == "vllm":
            backend_cfg = BackendConfig(
                type="vllm",
                model=config.model_id,
                endpoint=self.endpoint,
            )
            logger.info(f"Using vLLM backend at {self.endpoint}")
        else:
            backend_cfg = BackendConfig(
                type="pytorch",
                model=config.model_id,
                device="cuda",
                device_ids=[0],
            )
            logger.info("Using PyTorch backend")

        # Determine dataset/prompts
        if self.prompts_file:
            dataset_name = self.prompts_file
            logger.info(f"Using prompts file: {self.prompts_file}")
        else:
            # Use the dataset from YAML configs - EnergyStarAI/text_generation
            dataset_name = "EnergyStarAI/text_generation"
            logger.info(f"Using HuggingFace dataset: {dataset_name}")

        # Scenario configuration
        # Set token constraints based on reasoning mode
        is_reasoning = is_reasoning_enabled(config.reasoning_params)
        generate_kwargs = get_token_parameters(config.reasoning_params)

        scenario_cfg = ScenarioConfig(
            dataset_name=dataset_name,
            text_column_name="text",
            num_samples=self.num_prompts or 10,
            reasoning=is_reasoning,
            reasoning_params=config.reasoning_params if is_reasoning else None,
            generate_kwargs=generate_kwargs,
        )

        # Metrics configuration
        metrics_cfg = MetricsConfig(
            enabled=True,
            type="codecarbon",
            project_name=f"ai_energy_score_{config.model_id.replace('/', '_')}",
            output_dir=str(run_dir / "emissions"),
            country_iso_code="USA",
            region="california",
        )

        # Reporter configuration
        reporter_cfg = ReporterConfig(
            type="csv",
            output_file=str(run_dir / "benchmark_results.csv"),
        )

        # Build full config
        bench_config = BenchmarkConfig(
            name=f"ai_energy_score_{config.model_id}",
            backend=backend_cfg,
            scenario=scenario_cfg,
            metrics=metrics_cfg,
            reporter=reporter_cfg,
            output_dir=str(run_dir),
        )

        return bench_config

    def run_batch(
        self,
        model_name: Optional[str] = None,
        model_class: Optional[str] = None,
        task: Optional[str] = None,
        reasoning_state: Optional[str] = None,
    ) -> None:
        """Run batch benchmarks with optional filters.

        Args:
            model_name: Filter by model name (substring match)
            model_class: Filter by model class (A, B, or C)
            task: Filter by task type
            reasoning_state: Filter by reasoning state
        """
        print("=" * 80)
        print("AI Energy Score Batch Runner")
        print("=" * 80)

        # Parse CSV
        print(f"\nParsing models from: {self.csv_path}")
        parser = ModelConfigParser(self.csv_path)
        all_configs = parser.parse()
        print(f"  Found {len(all_configs)} model configurations")

        # Apply filters
        configs = parser.filter_configs(
            all_configs,
            model_name=model_name,
            model_class=model_class,
            task=task,
            reasoning_state=reasoning_state,
        )

        if not configs:
            print("\nNo models match the specified filters!")
            return

        print(f"  After filtering: {len(configs)} models to run")
        print(f"\nOutput directory: {self.output_dir}")
        print(f"Backend: {self.backend_type}")
        if self.backend_type == "vllm":
            print(f"Endpoint: {self.endpoint}")
        print(f"Prompts per model: {self.num_prompts or 'all'}")

        # Show models to run
        print("\nModels to run:")
        for i, config in enumerate(configs, 1):
            print(
                f"  {i}. {config.model_id} ({config.model_class}) - {config.reasoning_state}"
            )

        print("\n" + "=" * 80)

        # Run each model
        successful = 0
        failed = 0

        for i, config in enumerate(configs, 1):
            print(f"\n[{i}/{len(configs)}] Running: {config.model_id}")
            print(f"  Reasoning: {config.reasoning_state}")
            print("-" * 80)

            success = self.run_single_model(config)

            if success:
                successful += 1
                print("✓ SUCCESS")
            else:
                failed += 1
                print("✗ FAILED")

            print("-" * 80)

            # Add a small delay between models to allow cleanup to complete
            if i < len(configs):
                time.sleep(2)

        # Final summary
        print("\n" + "=" * 80)
        print("BATCH COMPLETE")
        print("=" * 80)
        print(f"Total models: {len(configs)}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"\nResults saved to: {self.output_dir / 'master_results.csv'}")
        print(f"Logs saved to: {self.logs_dir}")
        print("=" * 80)

        # Show aggregated summary
        summary = self.aggregator.get_results_summary()
        if summary:
            print("\nAggregated Summary:")
            for key, value in summary.items():
                if isinstance(value, float):
                    print(f"  {key}: {value:.4f}")
                else:
                    print(f"  {key}: {value}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AI Energy Score Batch Runner - Run benchmarks for multiple models"
    )

    parser.add_argument(
        "--csv",
        default="oct_2025_models.csv",
        help="Path to models CSV file",
    )
    parser.add_argument(
        "--output-dir",
        default="./batch_results",
        help="Output directory for results",
    )
    parser.add_argument(
        "--backend",
        choices=["vllm", "pytorch"],
        default="pytorch",
        help="Backend type (default: pytorch)",
    )
    parser.add_argument(
        "--endpoint",
        default="http://localhost:8000/v1",
        help="vLLM endpoint URL (for vllm backend)",
    )
    parser.add_argument(
        "--prompts-file",
        help="Path to prompts CSV file (optional, defaults to HuggingFace dataset EnergyStarAI/text_generation)",
    )
    parser.add_argument(
        "--num-prompts",
        type=int,
        help="Number of prompts to run (default: all prompts in file)",
    )

    # Filters
    parser.add_argument(
        "--model-name",
        help="Filter by model name (substring match)",
    )
    parser.add_argument(
        "--class",
        dest="model_class",
        help="Filter by model class (A, B, or C)",
    )
    parser.add_argument(
        "--task",
        help="Filter by task type (e.g., text_gen, image_gen)",
    )
    parser.add_argument(
        "--reasoning-state",
        help="Filter by reasoning state (e.g., 'On', 'Off', 'On (High)')",
    )

    args = parser.parse_args()

    # Create batch runner
    runner = BatchRunner(
        csv_path=args.csv,
        output_dir=args.output_dir,
        backend_type=args.backend,
        endpoint=args.endpoint,
        prompts_file=args.prompts_file,
        num_prompts=args.num_prompts,
    )

    # Run batch
    runner.run_batch(
        model_name=args.model_name,
        model_class=args.model_class,
        task=args.task,
        reasoning_state=args.reasoning_state,
    )


if __name__ == "__main__":
    main()
