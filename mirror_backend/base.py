from abc import ABC, abstractmethod

class MirrorBackend(ABC):
    @abstractmethod
    def start(self, serial_number: str, options: dict) -> None:
        """Mirroring begins."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop mirroring."""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Check if mirroring is running."""
        pass
