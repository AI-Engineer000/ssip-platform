def analyze_student(data, subjects):
    attendance = float(data[0])
    prevcgpa = float(data[1])
    sgpa = float(data[2])

    predicted = round((prevcgpa * 0.4) + (sgpa * 0.45) +
                      (attendance / 100 * 10 * 0.15), 2)
    predicted = max(0, min(predicted, 10))

    if predicted >= 9:
        category = "Excellent Performer"
    elif predicted >= 8:
        category = "Good Performer"
    elif predicted >= 7:
        category = "Average Performer"
    else:
        category = "Needs Improvement"

    weak = []
    if sgpa < 6.5:
        weak = subjects[:2]
    elif sgpa < 8:
        weak = subjects[:1]

    suggestions = []
    if attendance < 75:
        suggestions.append("Attendance is low — attend classes regularly.")
    if sgpa < 7:
        suggestions.append("Focus on weak subjects and increase practice.")
    if predicted < 7:
        suggestions.append(
            "Improve consistency — build a daily study routine.")
    if prevcgpa > sgpa:
        suggestions.append("Performance has dropped — identify weak subjects.")
    elif prevcgpa < sgpa:
        suggestions.append("Improvement detected! Maintain this momentum.")
    else:
        suggestions.append("Performance is stable — try to push further.")

    improved = round(min(predicted + 0.3, 10), 2)
    return predicted, category, weak, suggestions, improved
