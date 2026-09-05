"""Metric primitives, undefined policy and qualifier codes.

Contract: score_semantics (count-form F0.5, F1C truth table), undefined_policy
(null + reason code, never coercion to 0.0), aggregation (macro over defined
runs vs pooled ratio).
"""
NO_POSITIVES = "denominator_zero_no_positives"
NO_PREDICTIONS = "denominator_zero_no_predictions"
NO_OPPORTUNITY = "denominator_zero_no_decision_opportunity"
NO_CONTENT = "no_scored_decision_content"
NO_POINTS = "no_point_predictions_for_composite"
NO_EVENTS = "no_events_for_composite"
NO_DELAY = "no_detected_event_for_conditional_delay"
NO_REPORTING = "no_reporting_opportunity"
NO_DEFINED_RUN = "no_defined_run_in_cell"
NOT_APPLICABLE = "estimand_not_applicable_in_cell"

FALSE_ALARM_ONLY = "false_alarm_only_no_truth_positives"
NO_ALARM_ZERO = "no_alarm_raised_zero_by_count_form"
ZERO_COMPONENTS = "zero_components_defined"


def ratio(numerator, denominator, zero_code):
    """A zero denominator yields null plus a reason code, never 0.0."""
    if denominator == 0:
        return None, zero_code
    return numerator / denominator, None


def f_beta_half(tp, fp, fn):
    """Normative count form: F0.5 = 1.25TP / (1.25TP + 0.25FN + FP).

    Stays defined whenever the count denominator is positive, even where a
    component ratio is undefined. Null only when TP = FP = FN = 0.
    """
    denominator = 1.25 * tp + 0.25 * fn + fp
    if denominator == 0:
        return None, NO_CONTENT, None
    value = 1.25 * tp / denominator
    qualifier = None
    if tp == 0 and fp > 0 and fn == 0:
        qualifier = FALSE_ALARM_ONLY
    elif tp == 0 and fp == 0 and fn > 0:
        qualifier = NO_ALARM_ZERO
    return value, None, qualifier


def composite_f1c(point_precision, event_recall):
    """0.0 when both components are defined and at least one is zero."""
    if point_precision is None and event_recall is None:
        return None, NO_CONTENT, None
    if point_precision is None:
        return None, NO_POINTS, None
    if event_recall is None:
        return None, NO_EVENTS, None
    if point_precision == 0.0 or event_recall == 0.0:
        return 0.0, None, ZERO_COMPONENTS
    total = point_precision + event_recall
    return 2 * point_precision * event_recall / total, None, None


def confusion(tp, fp, fn, tn, unit, events=None, detected=None):
    """A full contract-shaped metric block for one native decision unit."""
    precision, precision_code = ratio(tp, tp + fp, NO_PREDICTIONS)
    recall, recall_code = ratio(tp, tp + fn, NO_POSITIVES)
    fpr, fpr_code = ratio(fp, fp + tn, NO_OPPORTUNITY)
    f05, f05_code, qualifier = f_beta_half(tp, fp, fn)
    if events:
        event_recall, event_code = ratio(detected or 0, events, NO_EVENTS)
    else:
        event_recall, event_code = None, NO_EVENTS
    f1c, f1c_code, f1c_qualifier = composite_f1c(precision, event_recall)
    return {
        "evaluation_unit": unit,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "precision_undefined_reason_code": precision_code,
        "recall": recall, "recall_undefined_reason_code": recall_code,
        "fpr": fpr, "fpr_undefined_reason_code": fpr_code,
        "f05": f05, "f05_undefined_reason_code": f05_code,
        "defined_value_qualifier_code": qualifier,
        "recallEvent": event_recall,
        "recallEvent_undefined_reason_code": event_code,
        "f1c": f1c, "f1c_undefined_reason_code": f1c_code,
        "f1c_defined_value_qualifier_code": f1c_qualifier,
        "events": events or 0, "detectedEvents": detected or 0,
    }


def macro_over_defined_runs(values):
    """Mean over the runs whose value is DEFINED, with both counts."""
    defined = [v for v in values if v is not None]
    if not defined:
        return None, NO_DEFINED_RUN, 0, len(values)
    return sum(defined) / len(defined), None, len(defined), len(values)


def pooled(numerators, denominators):
    total_den = sum(denominators)
    if total_den == 0:
        return None
    return sum(numerators) / total_den
