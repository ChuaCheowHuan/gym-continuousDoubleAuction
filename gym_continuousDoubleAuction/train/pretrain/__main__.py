"""`python -m gym_continuousDoubleAuction.train.pretrain`: says where the pretrainer went."""

import sys

from gym_continuousDoubleAuction.logging_setup import configure as configure_logging
from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.pretrain import MOVED

logger = get_logger("gym_continuousDoubleAuction.train.pretrain")


def main(argv=None) -> int:
    configure_logging(None)
    logger.error(MOVED)
    return 2


if __name__ == "__main__":
    sys.exit(main())
