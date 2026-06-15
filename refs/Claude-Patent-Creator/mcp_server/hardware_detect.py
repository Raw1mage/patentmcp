#!/usr/bin/env python3
"""
Hardware detection for automatic PyTorch installation
Detects GPU type and determines correct PyTorch version
"""

import platform
import subprocess


def detect_nvidia_gpu():
    """Detect if NVIDIA GPU is available"""
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def detect_apple_silicon():
    """Detect if running on Apple Silicon (M1/M2/M3)"""
    if platform.system() != "Darwin":
        return False
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5
        )
        return "Apple" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_pytorch_install_command():
    """
    Determine correct PyTorch installation command based on hardware

    Returns:
        tuple: (package_spec, index_url or None, description)
    """
    has_nvidia = detect_nvidia_gpu()
    has_apple_silicon = detect_apple_silicon()

    if has_nvidia:
        return (
            "torch>=2.0.0",
            "https://download.pytorch.org/whl/cu128",
            "[GPU] NVIDIA GPU detected - installing PyTorch with CUDA 12.8 support",
        )
    elif has_apple_silicon:
        return (
            "torch>=2.0.0",
            None,  # Default PyPI has MPS support
            "[GPU] Apple Silicon detected - installing PyTorch with MPS support",
        )
    else:
        return (
            "torch>=2.0.0",
            "https://download.pytorch.org/whl/cpu",
            "[CPU] No GPU detected - installing PyTorch CPU version",
        )


def check_pytorch_installation():
    """
    Check if PyTorch is installed and if it matches hardware

    Returns:
        dict: Status information about PyTorch installation
    """
    try:
        import torch

        has_nvidia = detect_nvidia_gpu()
        cuda_available = torch.cuda.is_available()

        status = {
            "installed": True,
            "version": torch.__version__,
            "cuda_available": cuda_available,
            "hardware_match": True,
        }

        # Check if NVIDIA GPU present but CUDA not available
        if has_nvidia and not cuda_available:
            status["hardware_match"] = False
            status["warning"] = "NVIDIA GPU detected but PyTorch has no CUDA support"

        # Check if Apple Silicon
        if detect_apple_silicon():
            try:
                mps_available = torch.backends.mps.is_available()
                status["mps_available"] = mps_available
            except AttributeError:
                status["mps_available"] = False

        return status

    except ImportError:
        return {
            "installed": False,
            "version": None,
            "cuda_available": False,
            "hardware_match": False,
        }
