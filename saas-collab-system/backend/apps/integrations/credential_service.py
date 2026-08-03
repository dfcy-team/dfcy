from rest_framework.exceptions import ValidationError


def validate_mock_credential_references(credential_id, token_id):
    if not isinstance(credential_id, str) or not credential_id.startswith("mock-credential-"):
        raise ValidationError("credential_id must be a synthetic mock credential reference.")
    if not isinstance(token_id, str) or not token_id.startswith("mock-token-"):
        raise ValidationError("token_id must be a synthetic mock token reference.")
    return credential_id, token_id


def mask_credential_references(credential_id, token_id):
    validate_mock_credential_references(credential_id, token_id)
    return {"credential": "mock-credential-***", "token": "mock-token-***"}


def rotate_credentials(*args, **kwargs):
    raise ValidationError(
        "Legacy encrypted credential rotation is retired; external reference rotation remains pending."
    )
