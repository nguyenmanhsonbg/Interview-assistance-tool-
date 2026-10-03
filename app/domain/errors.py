class DomainError(RuntimeError):
    code = "DOMAIN_ERROR"


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"


class StateConflict(DomainError):
    code = "STATE_CONFLICT"


class ResourceNotFound(DomainError):
    code = "RESOURCE_NOT_FOUND"


class UnsupportedMediaType(ValidationError):
    code = "UNSUPPORTED_MEDIA_TYPE"


class DocumentParseError(ValidationError):
    code = "DOCUMENT_PARSE_FAILED"


class Unauthenticated(DomainError):
    code = "UNAUTHENTICATED"


class ForbiddenCapability(DomainError):
    code = "FORBIDDEN_CAPABILITY"


class RevisionConflict(StateConflict):
    code = "ANSWER_REVISION_CONFLICT"


class BackupRequired(StateConflict):
    code = "BACKUP_REQUIRED"
