#!/usr/bin/env python3
"""
File watcher for Redator agent using polling.
Watches /data/in for bruto*.txt files and runs redator to produce /data/out/limpo.txt
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/agents/redator/src")

from redator.main import RedatorAgent
from agent_shared.schemas import RedatorConfig, AgenteRole

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "agent": "redator-watcher", "message": "%(message)s"}'
)
logger = logging.getLogger("redator-watcher")

IN_DIR = Path("/data/in")
OUT_DIR = Path("/data/out")


def main():
    logger.info(f"Starting redator watcher on {IN_DIR}")
    IN_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    config = RedatorConfig(
        role=AgenteRole.REDATOR,
        input_path="/data/in",
        output_path="/data/out",
        log_level="INFO"
    )
    agent = RedatorAgent(config)

    processed = set()

    while True:
        try:
            for bruto_path in IN_DIR.glob("bruto*.txt"):
                if bruto_path in processed:
                    continue
                if not bruto_path.is_file():
                    continue
                
                logger.info(f"Processing {bruto_path}")
                pipeline_id = bruto_path.stem
                limpo_path = OUT_DIR / f"{pipeline_id}_limpo.txt"
                
                try:
                    agent.processar(bruto_path, limpo_path)
                    logger.info(f"Completed redacao: {bruto_path} -> {limpo_path}")
                    processed.add(bruto_path)
                except Exception as e:
                    logger.error(f"Failed to process {bruto_path}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in watcher loop: {e}")
            
        time.sleep(2)


if __name__ == "__main__":
    main()