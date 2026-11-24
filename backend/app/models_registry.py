"""集中导入全部 ORM 模型，保证 Base.metadata 包含所有表。

Alembic 与测试建库都从这里取元数据，避免漏表。
"""

from app.modules.asset import models as asset_models  # noqa: F401
from app.modules.bench import models as bench_models  # noqa: F401
from app.modules.exec import models as exec_models  # noqa: F401
from app.modules.harness import models as harness_models  # noqa: F401
from app.modules.iam import models as iam_models  # noqa: F401
from app.modules.meta import models as meta_models  # noqa: F401
from app.modules.pipe import models as pipe_models  # noqa: F401
from app.modules.studio import models as studio_models  # noqa: F401
