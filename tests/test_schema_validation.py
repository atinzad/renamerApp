from app.domain.schema_validation import validate_schema_config


def test_validate_schema_valid_no_placeholders() -> None:
    errors = validate_schema_config('{"Name": "String"}', "")
    assert errors is None


def test_validate_schema_rejects_non_object() -> None:
    errors = validate_schema_config('["Name"]', "{Name}")
    assert errors is not None
    assert "must be an object" in errors[0]


def test_validate_schema_rejects_nested() -> None:
    errors = validate_schema_config('{"Name": {"First": "String"}}', "{Name}")
    assert errors is not None
    assert "primitive value" in errors[0]


def test_validate_schema_missing_placeholder() -> None:
    errors = validate_schema_config('{"Name": "String"}', "{Missing}")
    assert errors is not None
    assert "Missing" in errors[0]


def test_validate_schema_empty_schema_with_placeholder() -> None:
    errors = validate_schema_config("{}", "{Name}")
    assert errors is not None
    assert "placeholders but schema is empty" in errors[0]
