// ============================================================================
// Phase 16c — Client Type dropdown fix (FRONTEND)
// ============================================================================
//
// File: frontend/app/import/review/page.tsx
//
// THREE CHANGES:
//   1. Type change: client_types is RefItem[] not string[]
//   2. New component: CodeSelectCell (label shown / code saved)
//   3. Replace SelectCell with CodeSelectCell at two call sites
//
// ----------------------------------------------------------------------------
// CHANGE 1 — Type definitions (line 271 and line 293)
// ----------------------------------------------------------------------------
//
// In the RefData type around line 271, FIND:

  client_types: string[];

// REPLACE WITH:

  client_types: RefItem[];

// In the EMPTY_REF object around line 293, no change needed — the empty
// array [] satisfies RefItem[] just as well as string[]. But for clarity
// the line:

  client_types: [],

// stays exactly as-is.

// ----------------------------------------------------------------------------
// CHANGE 2 — Add CodeSelectCell component
// ----------------------------------------------------------------------------
//
// Add this NEW component immediately after the FkCell definition (around
// line 4400, after FkCell's closing brace). It's a copy of FkCell adapted
// to save a string code instead of a numeric id.

// ---- CodeSelectCell — picks a {code, name} pair, shows name, saves code ----
//
// Used for columns whose DB column holds a string code (constraint-checked)
// but whose dropdown should display a friendlier Vietnamese label.
//
// Example: tx_case.client_type_code holds "DU_HOC_FULL"; user sees
// "Du học (Ghi danh + visa)". Without this component, the dropdown would
// either save the display label (breaks check constraint) or display the
// raw code (unfriendly).
//
// Mirrors FkCell's structure exactly, only swapping numeric id for string
// code as the saved value.
function CodeSelectCell({
  value,
  options,
  onSave,
}: {
  value: string | null;
  options: RefItem[];
  onSave: (newCode: string | null) => Promise<void>;
}) {
  const { state, setState, error, setError, editing, setEditing } = useCellState();

  // Find the label for the currently saved code. Falls back to the raw code
  // if no match (e.g. legacy data with a code that's been removed from
  // ref_client_type — shouldn't happen but defends against it).
  const matched = options.find((o) => o.code === value);
  const labelFromOptions = matched?.name ?? null;

  // Optimistic local label override — same rationale as FkCell.
  const [localLabel, setLocalLabel] = useState<string | null>(null);
  const displayLabel = localLabel ?? labelFromOptions ?? value;

  const [draft, setDraft] = useState(displayLabel ?? '');

  useEffect(() => {
    setDraft(displayLabel ?? '');
  }, [displayLabel]);

  function cancel() {
    setEditing(false);
    setError(null);
    setDraft(displayLabel ?? '');
  }

  function pickByCode(newCode: string) {
    if (newCode === value) {
      setEditing(false);
      return;
    }
    const picked = options.find((o) => o.code === newCode);
    setLocalLabel(picked?.name ?? null);

    setState('saving');
    setError(null);
    onSave(newCode)
      .then(() => {
        setEditing(false);
        setState('idle');
      })
      .catch((e) => {
        setError(String(e instanceof Error ? e.message : e));
        setState('error');
        setLocalLabel(null);
      });
  }

  function clearValue() {
    if (value === null) {
      setEditing(false);
      return;
    }
    setLocalLabel(null);
    setState('saving');
    setError(null);
    onSave(null)
      .then(() => {
        setEditing(false);
        setState('idle');
      })
      .catch((e) => {
        setError(String(e instanceof Error ? e.message : e));
        setState('error');
      });
  }

  function commitDraft() {
    const trimmed = draft.trim();
    if (trimmed === '') {
      clearValue();
      return;
    }
    // Match by label, case-insensitive
    const match = options.find(
      (o) => (o.name ?? '').trim().toLowerCase() === trimmed.toLowerCase(),
    );
    if (!match || !match.code) {
      setError(`No matching option for "${trimmed}"`);
      setState('error');
      return;
    }
    pickByCode(match.code);
  }

  if (!editing) {
    return (
      <div
        className={EDITABLE_BASE}
        onClick={() => {
          setEditing(true);
          setError(null);
          setDraft(displayLabel ?? '');
        }}
      >
        {displayLabel || DASH}
      </div>
    );
  }

  const lcDraft = draft.trim().toLowerCase();
  const isUnchangedLabel = lcDraft === (displayLabel ?? '').trim().toLowerCase();
  const filtered =
    lcDraft && !isUnchangedLabel
      ? options.filter((o) => (o.name ?? '').toLowerCase().includes(lcDraft))
      : options;

  const CLEAR_KEY = '__clear__';

  const dropdownOptions = [
    ...(value !== null
      ? [{ key: CLEAR_KEY, label: '— Clear assignment —', isCurrent: false }]
      : []),
    ...filtered.map((o) => ({
      key: o.code ?? '',
      label: o.name ?? '',
      isCurrent: o.code === value,
    })),
  ];

  return (
    <div className="relative">
      <SearchableDropdown
        open={editing}
        setOpen={(o) => {
          if (!o) cancel();
        }}
        options={dropdownOptions}
        draft={draft}
        setDraft={setDraft}
        onPick={(key) => {
          if (key === CLEAR_KEY) {
            clearValue();
          } else {
            pickByCode(key);
          }
        }}
        onCancel={cancel}
        onCommitDraft={commitDraft}
        placeholder={`type to search… (${options.length} options)`}
        saving={state === 'saving'}
      />
      <ErrorTooltip error={error} />
    </div>
  );
}

// ----------------------------------------------------------------------------
// CHANGE 3a — Replace SelectCell with CodeSelectCell (column definition,
//             around line 2138)
// ----------------------------------------------------------------------------
//
// FIND this column definition (around line 2131-2145):

      {
        id: 'client_type_code',
        header: 'Client Type',
        accessorFn: (row) => row.client_type_code ?? '',
        size: 200,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <SelectCell
              value={c.client_type_code}
              options={refData.client_types}
              onSave={(v) => onSave(c.id, { client_type_code: v })}
            />
          );
        },
      },

// REPLACE the <SelectCell ... /> block with <CodeSelectCell ... />:

      {
        id: 'client_type_code',
        header: 'Client Type',
        accessorFn: (row) => row.client_type_code ?? '',
        size: 200,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <CodeSelectCell
              value={c.client_type_code}
              options={refData.client_types}
              onSave={(v) => onSave(c.id, { client_type_code: v })}
            />
          );
        },
      },

// ----------------------------------------------------------------------------
// CHANGE 3b — Same replacement at the second site (around line 3271)
// ----------------------------------------------------------------------------
//
// There's a second instance of the same dropdown elsewhere in the page —
// probably the detail drawer or row-detail panel.
//
// FIND (around line 3271):

            <SelectCell
              value={c.client_type_code}
              options={refData.client_types}
              onSave={(v) => save({ client_type_code: v })}
            />

// REPLACE WITH:

            <CodeSelectCell
              value={c.client_type_code}
              options={refData.client_types}
              onSave={(v) => save({ client_type_code: v })}
            />

// ----------------------------------------------------------------------------
// VERIFICATION (after both backend + frontend deployed)
// ----------------------------------------------------------------------------
//
// 1. Reload the Review Board.
// 2. Click the Client Type cell on SLC-12635 (or any case).
// 3. Dropdown shows 10 Vietnamese labels (not 65 fuzzy variants).
// 4. Pick "Du học (Ghi danh + visa)".
// 5. Cell shows that label; no constraint error.
// 6. Refresh the page — value persists.
// 7. Verify in DB:
//      SELECT contract_id, client_type_code FROM tx_case WHERE contract_id = 'SLC-12635';
//    Should show:
//      SLC-12635 | DU_HOC_FULL
