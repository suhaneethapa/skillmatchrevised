def compute_match_score(student_skills, internship_skills):
    if not internship_skills:
        return 0.0, []
    
    required_weight = 2.0
    preferred_weight = 1.0
    
    weighted_total = 0.0
    weighted_intersection = 0.0
    skills_gap = []
    student_set = set(student_skills)
    
    for skill_name, is_required in internship_skills:
        weight = required_weight if is_required else preferred_weight
        weighted_total += weight
        if skill_name in student_set:
            weighted_intersection += weight
        elif is_required:
            skills_gap.append(skill_name)
    
    if weighted_total == 0:
        return 0.0, skills_gap
    
    match_score = (weighted_intersection / weighted_total) * 100
    return round(match_score, 2), skills_gap


def is_eligible(match_score, threshold=50.0):
    return match_score >= threshold


def explain_match(student, internship):
    """
    Returns an explainable breakdown of a student's match for an internship.
    Uses the canonical 2.0 (required) / 1.0 (preferred) weighted coverage formula
    and 50.0% eligibility threshold.

    Arguments can be:
      - student: User model instance, StudentProfile, or iterable of skill names.
      - internship: Internship model instance or iterable of (skill_name, is_required) tuples.
    """
    # 1. Resolve student skills set
    if hasattr(student, 'student_skills'):
        student_set = set(student.student_skills.values_list('skill__name', flat=True))
    elif hasattr(student, 'user') and hasattr(student.user, 'student_skills'):
        student_set = set(student.user.student_skills.values_list('skill__name', flat=True))
    elif isinstance(student, (set, list, tuple)):
        student_set = set(student)
    else:
        student_set = set()

    # 2. Resolve internship skill requirements
    if hasattr(internship, 'internship_skills'):
        req_tuples = [
            (s.skill.name, s.is_required)
            for s in internship.internship_skills.all()
        ]
    elif isinstance(internship, (list, tuple)):
        req_tuples = list(internship)
    else:
        req_tuples = []

    # 3. Calculate canonical match score and gap
    score, gap = compute_match_score(student_set, req_tuples)
    eligible = is_eligible(score)

    matched_required = []
    missing_required = []
    matched_preferred = []
    missing_preferred = []

    for name, is_req in req_tuples:
        if is_req:
            if name in student_set:
                matched_required.append(name)
            else:
                missing_required.append(name)
        else:
            if name in student_set:
                matched_preferred.append(name)
            else:
                missing_preferred.append(name)

    # 4. Generate a concise, human-understandable explanation
    total_req = len(matched_required) + len(missing_required)
    total_pref = len(matched_preferred) + len(missing_preferred)

    if not req_tuples:
        explanation = "No specific skill prerequisites are listed for this role."
    elif score == 100.0:
        explanation = "Excellent match (100%). Candidate possesses all required and preferred competencies."
    elif eligible:
        if not missing_required:
            explanation = f"Eligible ({score}%). Candidate matches all required skills ({len(matched_required)}/{total_req}) and meets the 50% threshold."
        else:
            explanation = f"Eligible ({score}%). Meets the 50% threshold with {len(matched_required)} of {total_req} required skills matched."
    else:
        if missing_required:
            explanation = f"Below 50% threshold ({score}%). Missing required competencies: {', '.join(missing_required)}."
        else:
            explanation = f"Below 50% threshold ({score}%). Additional preferred competencies needed to reach eligibility."

    return {
        'score': score,
        'eligible': eligible,
        'gap': missing_required,
        'matched_required': matched_required,
        'missing_required': missing_required,
        'matched_preferred': matched_preferred,
        'missing_preferred': missing_preferred,
        'total_required': total_req,
        'total_preferred': total_pref,
        'explanation': explanation,
    }
