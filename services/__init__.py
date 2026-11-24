# -*- coding: utf-8 -*-
"""Modularni servisi AI Influencer Studija (1.1.0).

- hardware_service: GPU detekcija, RX 6600 profil, ComfyUI zastavice i okruženje (ZLUDA/ROCm)
- generation_service: predlošci, opcije workflowa, red čekanja, galerija, LoRA dataset, Character Sheet
- posting_service: Instagram/Facebook (Meta Graph), Telegram, Premium API, kalendar i scheduler
- crm_service: inbox, memorija po fanu, interes, AI chat, custom narudžbe, pretplatnici, analitika
- lora_trainer_service: character LoRA trener (dataset, 8 GB postavke, sd-scripts, temperatura GPU-a, auto-dodavanje osobi)

Postojeći moduli (studio.py, image_gen.py, inbox.py, character.py, comfy_launch.py ...) i dalje rade
kao prije i delegiraju ovdje.
"""

from __future__ import annotations

from . import hardware_service, generation_service, posting_service, crm_service, lora_trainer_service  # noqa: F401

__all__ = ["hardware_service", "generation_service", "posting_service", "crm_service", "lora_trainer_service", "init_schema", "start_workers", "stop_workers"]


def init_schema() -> None:
    generation_service.ensure_schema()
    posting_service.ensure_schema()
    crm_service.ensure_schema()
    lora_trainer_service.ensure_schema()


def start_workers() -> None:
    generation_service.start_worker()
    posting_service.start_scheduler()


def stop_workers() -> None:
    generation_service.stop_worker()
    posting_service.stop_scheduler()
    try:
        lora_trainer_service.stop_all()
    except Exception:
        pass
