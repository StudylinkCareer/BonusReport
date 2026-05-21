-- ============================================================================
-- Add Quan Hoàng Yến's missing 2025-05 and 2025-06 targets.
-- Confirmed by RP: target = 3 enrolments for both months.
-- ============================================================================

BEGIN;

SELECT 'Adding Yến 2025-05 and 2025-06 target rows' AS section;

INSERT INTO ref_staff_target
  (staff_id, role_id, office_id, year, month, target, target_type, target_unit)
SELECT
  s.id,
  r.id,
  o.id,
  v.year,
  v.month,
  3,
  'ENROLMENT',
  'COUNT'
FROM (VALUES (2025, 5), (2025, 6)) AS v(year, month)
CROSS JOIN ref_staff s
CROSS JOIN dim_role r
CROSS JOIN dim_office o
WHERE s.canonical_name = 'Quan Hoàng Yến'
  AND r.code = 'CO_DIR'
  AND o.code = 'HCM'
  AND NOT EXISTS (
    SELECT 1 FROM ref_staff_target t
     WHERE t.staff_id = s.id
       AND t.role_id  = r.id
       AND t.office_id = o.id
       AND t.year = v.year
       AND t.month = v.month
  );

-- Verify both rows are present
SELECT s.canonical_name, o.code AS office, r.code AS role,
       t.year, t.month, t.target
  FROM ref_staff_target t
  JOIN ref_staff s ON s.id = t.staff_id
  JOIN dim_office o ON o.id = t.office_id
  JOIN dim_role r ON r.id = t.role_id
 WHERE s.canonical_name = 'Quan Hoàng Yến'
   AND t.year = 2025 AND t.month IN (5, 6)
 ORDER BY t.month;

COMMIT;
