from jinja2 import Environment, StrictUndefined, meta
from jinja2.sandbox import SandboxedEnvironment

_ENV: Environment = SandboxedEnvironment(
    autoescape=False,
    trim_blocks=False,
    lstrip_blocks=False,
    undefined=StrictUndefined,
)


def render_template(template: str, values: dict[str, str]) -> str:
    """使用标准 Jinja2 语法渲染命名模板。"""

    return _ENV.from_string(str(template or "")).render(**values)


def collect_template_fields(template: str) -> set[str]:
    ast = _ENV.parse(str(template or ""))
    return set(meta.find_undeclared_variables(ast))
