"""Runtime patch for a2a-sdk 1.0.2 protobuf C-extension incompatibility.

The SDK's ``validate_proto_required_fields`` (and ``_recurse_validation``)
call ``field.label`` on a protobuf ``FieldDescriptor``, which the modern
C-extension (protobuf >=5.x) no longer exposes. Every ``message/send``
request crashes with ``AttributeError: 'google._upb._message.FieldDescriptor'
object has no attribute 'label'``.

The SDK has a TODO at the call sites to switch to ``field.is_repeated``
(see https://github.com/a2aproject/a2a-python/issues/1011) but 1.0.2
hasn't shipped the fix. We patch both functions in-place at import time.
Idempotent — calling twice is a no-op.
"""

from a2a.utils import proto_utils
from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.message import Message as ProtobufMessage


def patch_a2a_sdk_protobuf_compat() -> None:
    """Replace ``field.label`` reads with ``field.is_repeated``."""
    if getattr(proto_utils, "_vystak_label_compat_applied", False):
        return

    def _check_required_field_violation(msg, field):  # noqa: ANN001
        val = getattr(msg, field.name)
        if field.is_repeated:
            if not val:
                return proto_utils.ValidationDetail(
                    field=field.name,
                    message="Field must contain at least one element.",
                )
        elif field.has_presence:
            if not msg.HasField(field.name):
                return proto_utils.ValidationDetail(
                    field=field.name, message="Field is required."
                )
        elif val == field.default_value:
            return proto_utils.ValidationDetail(
                field=field.name, message="Field is required."
            )
        return None

    def _recurse_validation(msg, field):  # noqa: ANN001
        errors: list[proto_utils.ValidationDetail] = []
        if field.type != FieldDescriptor.TYPE_MESSAGE:
            return errors

        val = getattr(msg, field.name)
        if not field.is_repeated:
            if msg.HasField(field.name):
                sub_errs = proto_utils._validate_proto_required_fields_internal(val)
                proto_utils._append_nested_errors(errors, field.name, sub_errs)
        elif field.message_type.GetOptions().map_entry:
            for k, v in val.items():
                if isinstance(v, ProtobufMessage):
                    sub_errs = proto_utils._validate_proto_required_fields_internal(v)
                    proto_utils._append_nested_errors(
                        errors, f"{field.name}[{k}]", sub_errs
                    )
        else:
            for i, item in enumerate(val):
                sub_errs = proto_utils._validate_proto_required_fields_internal(item)
                proto_utils._append_nested_errors(
                    errors, f"{field.name}[{i}]", sub_errs
                )
        return errors

    proto_utils._check_required_field_violation = _check_required_field_violation
    proto_utils._recurse_validation = _recurse_validation
    proto_utils._vystak_label_compat_applied = True
