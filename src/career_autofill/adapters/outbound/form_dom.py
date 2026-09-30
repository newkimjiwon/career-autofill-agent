"""Read-only DOM extraction shared by full snapshots and per-control guards."""

from ...domain.models import FormField
from ...domain.policies import check_url

CONTROL_SELECTOR = "input,select,textarea"
READ_CONTROL_SCRIPT = """(e, index) => {
  if (!e.getClientRects().length || getComputedStyle(e).visibility === 'hidden') return null;
  const labelText = node => node.nodeType === 3 ? node.textContent :
    (['INPUT','SELECT','TEXTAREA','BUTTON'].includes(node.tagName) ? '' :
      [...node.childNodes].map(labelText).join(''));
  const explicit = [...(e.labels || [])].map(l => labelText(l).trim())
    .filter(Boolean).join(' ');
  const labelled = (e.getAttribute('aria-labelledby') || '').split(' ')
    .map(id => document.getElementById(id)?.innerText || '').join(' ').trim();
  const container = e.closest('fieldset,section,[role=group],.form-group');
  const section = container?.querySelector('legend,h2,h3,h4')?.innerText || '';
  return {index, label: explicit || e.getAttribute('aria-label') || labelled ||
           e.getAttribute('placeholder') || '', section,
    kind: e.tagName === 'TEXTAREA' ? 'textarea' : e.type,
    name: e.name || '', value: e.type === 'password' ? '' : (e.value || ''),
    required: e.required || e.getAttribute('aria-required') === 'true',
    disabled: e.disabled, readonly: !!e.readOnly, maxlength: e.maxLength ?? -1,
    format_hint: location.pathname.startsWith('/v1/applicant/resume-form/') &&
      /^(입학년월|졸업년월|입대년월|제대년월)$/.test(e.placeholder || '') ? 'YYYY.MM' : '',
    options: e.tagName === 'SELECT' ?
      [...e.options].map(o => ({label:o.text, value:o.value})) : []};
}"""

SCAN_SCRIPT = """() => {
 const readControl = __READ_CONTROL__;
 return [...document.querySelectorAll('input,select,textarea')].flatMap((e, index) => {
   const field = readControl(e, index);
   return field ? [field] : [];
 });
}""".replace("__READ_CONTROL__", READ_CONTROL_SCRIPT)


async def scan_fields(page) -> list[FormField]:
    check_url(page.url, application=True)
    result = []
    for frame_number, frame in enumerate(page.frames):
        # Ignore embedded third-party login/analytics/payment frames.
        if frame.url and frame.url != "about:blank":
            try:
                check_url(frame.url, application=True)
            except ValueError:
                continue
        for field in await frame.evaluate(SCAN_SCRIPT):
            result.append(
                FormField(
                    id=f"f{frame_number}:{field['index']}",
                    frame=frame_number,
                    **field,
                )
            )
    return result
