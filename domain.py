from enum import StrEnum


class EventStatus(StrEnum):
    PUBLISHED = "published"
    FINISHED = "finished"
    REGISTRATION_CLOSED = "registration_closed"


class EventNotFound(Exception):
    pass


class TicketNotFound(Exception):
    pass


class RegistrationClosed(Exception):
    pass


class ProviderRejected(Exception):
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text
        super().__init__(text)
