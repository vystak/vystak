"""Native a2a-sdk based A2A integration.

Importing this package applies a runtime monkey-patch to a2a-sdk 1.0.2's
``proto_utils._check_required_field_violation`` and ``_recurse_validation``
so they use ``field.is_repeated`` instead of the deprecated ``field.label``.
The SDK has a TODO to bump (issue 1011) but 1.0.2 hasn't shipped the fix
and ``field.label`` was removed in protobuf C-extension >=5.x — without
the patch every ``message/send`` request raises
``AttributeError: 'FieldDescriptor' object has no attribute 'label'``.
"""

from _vystak.runtime.a2a_native._sdk_compat import patch_a2a_sdk_protobuf_compat

patch_a2a_sdk_protobuf_compat()
