import { SOURCE_CAPABILITIES, SOURCE_ROLES } from "@/lib/research-api";
import {
  PURPOSE_QUESTION,
  SOURCE_CAPABILITY_LABELS,
  SOURCE_ROLE_LABELS,
  evidenceAllowed,
} from "@/lib/source-purpose";

// Shared purpose inputs for the register form and the per-row editor. Plain
// form fields only: the server action validates every value again.
export function PurposeFields({
  primaryRole = "inspiration",
  capabilities = ["inspiration"],
  label,
}: {
  primaryRole?: string;
  capabilities?: readonly string[];
  label?: string;
}) {
  const suffix = label ? ` (${label})` : "";
  return (
    <>
      <label>
        Birincil rol
        <select
          name="primary_role"
          required
          defaultValue={primaryRole}
          aria-label={`Birincil rol${suffix}`}
        >
          {SOURCE_ROLES.map((role) => (
            <option key={role} value={role}>
              {SOURCE_ROLE_LABELS[role]}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="purpose-fieldset">
        <legend>{PURPOSE_QUESTION}</legend>
        <div className="purpose-options">
          {SOURCE_CAPABILITIES.map((capability) => (
            <label key={capability} className="purpose-option">
              <input
                type="checkbox"
                name="capabilities"
                value={capability}
                defaultChecked={capabilities.includes(capability)}
                aria-label={`${SOURCE_CAPABILITY_LABELS[capability]}${suffix}`}
              />
              {SOURCE_CAPABILITY_LABELS[capability]}
            </label>
          ))}
        </div>
        <p className="muted purpose-hint">
          Hiçbiri seçilmezse birincil rolün varsayılan sinyal aileleri
          kullanılır; kaynak tek bir role kilitlenmez.
          {!evidenceAllowed(primaryRole) &&
            " Topluluk kaynakları asla araştırma kanıtı üretmez."}
        </p>
      </fieldset>
    </>
  );
}
