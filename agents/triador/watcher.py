#!/usr/bin/env python3
"""
File watcher for Triador agent using polling.
Watches /data/out for *_limpo.txt files and runs triador
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/agents/triador/src")

from triador.main import TriadorAgent
from agent_shared.schemas import TriadorConfig, AgenteRole

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "agent": "triador-watcher", "message": "%(message)s"}'
)
logger = logging.getLogger("triador-watcher")

IN_DIR = Path("/data/out")


def main():
    logger.info(f"Starting triador watcher on {IN_DIR}")
    IN_DIR.mkdir(parents=True, exist_ok=True)

    config = TriadorConfig(
        role=AgenteRole.TRIADOR,
        input_path="/data/in",
        output_path="/data/out",
        modelo_classificacao="keyword",
        threshold_confianca=0.7,
        log_level="INFO"
    )
    agent = TriadorAgent(config)

    processed = set()

    while True:
        try:
            for limpo_path in IN_DIR.glob("*_limpo.txt"):
                if limpo_path in processed:
                    continue
                if not limpo_path.is_file():
                    continue
                
                logger.info(f"Processing {limpo_path}")
                try:
                    agent.processar(limpo_path)
                    logger.info(f"Completed triagem: {limpo_path}")
                    processed.add(limpo_path)
                except Exception as e:
                    logger.error(f"Failed to process {limpo_path}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in watcher loop: {e}")
            
        time.sleep(2)


if __name__ == "__main__":
    main()