#!/usr/bin/env python3
"""
File watcher for Especialista agent using polling.
Watches /data/out for *.classificacao.json files with ambíguo=true
"""
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/agents/especialista/src")

from especialista.main import EspecialistaAgent
from agent_shared.schemas import EspecialistaConfig, AgenteRole

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "agent": "especialista-watcher", "message": "%(message)s"}'
)
logger = logging.getLogger("especialista-watcher")

IN_DIR = Path("/data/out")


def main():
    logger.info(f"Starting especialista watcher on {IN_DIR}")
    IN_DIR.mkdir(parents=True, exist_ok=True)

    config = EspecialistaConfig(
        role=AgenteRole.ESPECIALISTA,
        input_path="/data/in",
        output_path="/data/out",
        usar_llm=False,
        modelo_llm="gpt-4",
        log_level="INFO"
    )
    agent = EspecialistaAgent(config)

    processed = set()

    while True:
        try:
            for classif_path in IN_DIR.glob("*.classificacao.json"):
                if classif_path in processed:
                    continue
                if not classif_path.is_file():
                    continue
                
                # Check if ambíguo
                try:
                    with open(classif_path) as f:
                        data = json.load(f)
                    if data.get("ambíguo") != True:
                        continue
                except Exception:
                    continue
                
                logger.info(f"Processing {classif_path}")
                try:
                    agent.processar(classif_path)
                    logger.info(f"Completed analise: {classif_path}")
                    processed.add(classif_path)
                except Exception as e:
                    logger.error(f"Failed to process {classif_path}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in watcher loop: {e}")
            
        time.sleep(2)


if __name__ == "__main__":
    main()