from enum import Enum
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel, TypeAdapter

from contenthive.models.plugin import SettingFieldType, SettingItem

_PYTHON_TYPE_TO_FIELD_TYPE: dict[type, SettingFieldType] = {
    str: SettingFieldType.STRING,
    int: SettingFieldType.INTEGER,
    float: SettingFieldType.FLOAT,
    bool: SettingFieldType.BOOLEAN,
}


def _literal_options(annotation: Any) -> list[str] | None:
    if get_origin(annotation) is Literal:
        return list(get_args(annotation))
    return None


def _resolve_field_type(annotation: Any) -> tuple[SettingFieldType, list[str] | None]:
    literal_options = _literal_options(annotation)
    if literal_options is not None:
        return SettingFieldType.ENUM, literal_options

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return SettingFieldType.ENUM, [e.value for e in annotation]

    return _PYTHON_TYPE_TO_FIELD_TYPE.get(annotation, SettingFieldType.STRING), None


def schema_class_to_setting_items(schema_cls: type[BaseModel], config_obj: BaseModel) -> list[SettingItem]:
    """Convert a Pydantic schema class and current config object into SettingItem list."""
    items: list[SettingItem] = []
    for field_name, field_info in schema_cls.model_fields.items():
        annotation = field_info.annotation
        field_type, options = _resolve_field_type(annotation)
        label = field_info.title or field_name
        extra = field_info.json_schema_extra or {}
        secret = bool(extra.get("secret", False))
        required = field_info.is_required()
        default = None if required or field_info.default_factory is not None else field_info.default
        if isinstance(default, Enum):
            default = default.value

        raw_value = getattr(config_obj, field_name, None)
        if isinstance(raw_value, Enum):
            raw_value = raw_value.value

        items.append(
            SettingItem(
                key=field_name,
                type=field_type,
                label=label,
                description=field_info.description,
                required=required,
                secret=secret,
                default=default,
                options=options,
                value=raw_value,
            )
        )
    return items


def validate_partial_config(
    schema_cls: type[BaseModel],
    incoming: dict[str, Any],
    stored: dict[str, Any] | None = None,
    reserved_keys: set[str] | None = None,
) -> list[str]:
    """Validate a partial config dict against a Pydantic schema class."""
    errors: list[str] = []
    reserved = reserved_keys or set()

    for key in incoming:
        if key in reserved:
            errors.append(f"Key '{key}' is reserved and cannot be set via API")

    declared_fields = schema_cls.model_fields

    for key, value in incoming.items():
        if key in reserved or key not in declared_fields:
            continue
        field_info = declared_fields[key]
        annotation = field_info.annotation
        literal_options = _literal_options(annotation)
        if literal_options is not None:
            if value not in literal_options:
                errors.append(f"Key '{key}': '{value}' is not a valid option, must be one of {literal_options}")
        elif isinstance(annotation, type) and issubclass(annotation, Enum):
            valid_values = [e.value for e in annotation]
            if value not in valid_values:
                errors.append(f"Key '{key}': '{value}' is not a valid option, must be one of {valid_values}")
        else:
            try:
                TypeAdapter(annotation).validate_python(value, strict=True)
            except Exception:
                expected = getattr(annotation, "__name__", str(annotation))
                actual = type(value).__name__
                errors.append(f"Key '{key}': expected {expected}, got {actual} ({value!r})")

    satisfied = {k for k in incoming if k in declared_fields}
    if stored:
        satisfied |= {k for k in stored if k in declared_fields}
    for field_name, field_info in declared_fields.items():
        if field_info.is_required() and field_name not in satisfied:
            errors.append(f"Required field '{field_name}' is missing")

    return errors
