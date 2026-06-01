def build_grid(enrollments):
    DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    
    # Define hour blocks starting points
    HOURS = ['08:00', '09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '16:00', '17:00']
    
    # Initialize grid: grid[hour_index][day] = None or {'section': ..., 'rowspan': 2, 'skip': False}
    grid = {h: {d: None for d in DAYS} for h in HOURS}
    
    for enr in enrollments:
        day = enr['day']
        time_str = enr['time'] # e.g. "08:00 - 10:00"
        start, end = [t.strip() for t in time_str.split('-')]
        
        # simple parsing
        start_h = int(start.split(':')[0])
        end_h = int(end.split(':')[0])
        span = end_h - start_h
        
        # place in grid
        if start in grid:
            grid[start][day] = {'course': enr['course'], 'span': span, 'type': enr['type']}
            
            # mark following hours as skipped
            for h in range(start_h + 1, end_h):
                h_str = f"{h:02d}:00"
                if h_str in grid:
                    grid[h_str][day] = 'SKIP'
                    
    return grid

print(build_grid([
    {'day': 'Monday', 'time': '08:00 - 10:00', 'course': 'CS101', 'type': 'Lecture'},
    {'day': 'Monday', 'time': '10:00 - 11:00', 'course': 'CS101', 'type': 'Tutorial'},
    {'day': 'Wednesday', 'time': '14:00 - 16:00', 'course': 'SE301', 'type': 'Lecture'}
]))
