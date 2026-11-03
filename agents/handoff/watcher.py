#!/usr/bin/env python3
"""
File watcher for Handoff agent using polling.
Watches /data/out for *.classificacao.json files and runs handoff
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/agents/handoff/src")

from handoff.main import HandoffAgent
from agent_shared.schemas import HandoffConfig, AgenteRole

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "agent": "handoff-watcher", "message": "%(message)s"}'
)
logger = logging.getLogger("handoff-watcher")

IN_DIR = Path("/data/out")


def main():
    logger.info(f"Starting handoff watcher on {IN_DIR}")
    IN_DIR.mkdir(parents=True, exist_ok=True)

    config = HandoffConfig(
        role=AgenteRole.HANDOFF,
        input_path="/data/in",
        output_path="/data/out",
        canais=["slack", "jira"],
        slack_webhook_url="",
        jira_project_key="INC",
        log_level="INFO"
    )
    agent = HandoffAgent(config)

    processed = set()

    while True:
        try:
            for classif_path in IN_DIR.glob("*.classificacao.json"):
                if classif_path in processed:
                    continue
                if not classif_path.is_file():
                    continue
                
                analise_path = classif_path.with_name(classif_path.stem + ".analise.json")
                
                logger.info(f"Processing handoff for {classif_path}")
                try:
                    agent.processar(classif_path, analise_path if analise_path.exists() else None)
                    logger.info(f"Completed handoff: {classif_path}")
                    processed.add(classif_path)
                except Exception as e:
                    logger.error(f"Failed to process {classif_path}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in watcher loop: {e}")
            
        time.sleep(2)


if __name__ == "__main__":
    main()