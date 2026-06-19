#!/usr/bin/env python3
"""Parse FamilyScript (.txt) into JSON for the family tree visualizer."""

import json
import sys
import re
from pathlib import Path

INDIVIDUAL_TAGS = {
    'p': 'given_names', 'n': 'given_names_birth', 'N': 'nickname',
    'T': 'title', 'J': 'suffix', 'l': 'surname', 'q': 'surname_birth',
    'R': 'pet_type', 'g': 'gender', 'b': 'birth_date', 'z': 'deceased',
    'd': 'death_date', 'r': 'photo', 'G': 'color_label', 'O': 'birth_order',
    'm': 'mother', 'f': 'father', 'V': 'parent_set_type',
    's': 'partner', 'X': 'mother2', 'Y': 'father2', 'W': 'parent_set2_type',
    'K': 'mother3', 'L': 'father3', 'Q': 'parent_set3_type',
    'e': 'email', 'w': 'website', 'B': 'blog', 'P': 'photo_site',
    't': 'home_tel', 'k': 'work_tel', 'u': 'mobile',
    'a': 'address', 'C': 'other_contact',
    'v': 'birth_place', 'y': 'death_place', 'Z': 'cause_of_death',
    'U': 'burial_place', 'F': 'burial_date',
    'j': 'profession', 'E': 'company', 'I': 'interests',
    'A': 'activities', 'o': 'bio_notes',
    '^': 'focus_person',
}

PARTNERSHIP_TAGS = {
    'e': 'partner_status', 'g': 'partnership_type',
    'b': 'start_date', 'r': 'engagement_date',
    'm': 'marriage_date', 'w': 'marriage_location',
    't': 'restart_date', 'n': 'remarriage_date', 'y': 'remarriage_location',
    's': 'separation_date', 'd': 'divorce_date', 'a': 'annulment_date',
    'f': 'first_end_date', 'z': 'end_date',
}

PARTNERSHIP_TYPE_MAP = {
    'm': 'married', 'e': 'engaged', 'r': 'relationship', 'f': 'friendship',
    'd': 'divorced', 's': 'separated', 'a': 'annulled', 'n': 'remarried',
    'c': 'reconciled', '': 'relationship',
}


def unescape(s):
    return s.replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')


def parse_date(d):
    if not d:
        return None
    bce = d.startswith('B')
    if bce:
        d = d[1:]
    suffix = ''
    if d and d[-1] in '~><':
        suffix = d[-1]
        d = d[:-1]
    if '-' in d and len(d) > 8:
        return d  # date range, keep as-is
    y = d[:4] if len(d) >= 4 else d
    m = d[4:6] if len(d) >= 6 else '00'
    day = d[6:8] if len(d) >= 8 else '00'
    parts = []
    yi = int(y) if y else 0
    mi = int(m) if m else 0
    di = int(day) if day else 0
    if yi:
        parts.append(f"{'BCE ' if bce else ''}{yi}")
    if mi:
        months = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        parts.append(months[mi] if mi <= 12 else str(mi))
    if di:
        parts.append(str(di))
    result = ' '.join(parts)
    if suffix == '~':
        result = f"~{result}"
    elif suffix == '>':
        result = f"before {result}"
    elif suffix == '<':
        result = f"after {result}"
    return result or None


def parse_familyscript(text):
    individuals = {}
    partnerships = []

    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        if line.startswith('i'):
            parts = line.split('\t')
            person_id = parts[0][1:]  # strip 'i'
            if person_id not in individuals:
                individuals[person_id] = {'id': person_id}
            person = individuals[person_id]
            for field in parts[1:]:
                if not field:
                    continue
                tag = field[0]
                data = unescape(field[1:])
                key = INDIVIDUAL_TAGS.get(tag)
                if key:
                    person[key] = data

        elif line.startswith('p'):
            parts = line.split('\t')
            header = parts[0]
            ids = header[1:].split(' ')
            if len(ids) != 2:
                continue
            partnership = {'person1': ids[0], 'person2': ids[1]}
            for field in parts[1:]:
                if not field:
                    continue
                tag = field[0]
                data = unescape(field[1:])
                key = PARTNERSHIP_TAGS.get(tag)
                if key:
                    partnership[key] = data
            partnerships.append(partnership)

    # Build nodes and edges
    nodes = []
    edges = []
    seen_edges = set()

    for pid, p in individuals.items():
        gender_raw = p.get('gender', '')
        gender = {'m': 'male', 'f': 'female'}.get(gender_raw, 'other')

        display_name = ''
        given = p.get('given_names', '')
        surname = p.get('surname', '')
        if given and surname:
            display_name = f"{surname}{given}" if _is_cjk(surname) or _is_cjk(given) else f"{given} {surname}"
        elif given:
            display_name = given
        elif surname:
            display_name = surname
        else:
            display_name = pid

        birth_display = parse_date(p.get('birth_date', ''))
        death_display = parse_date(p.get('death_date', ''))

        node = {
            'id': pid,
            'name': display_name,
            'given_names': given,
            'surname': surname,
            'surname_birth': p.get('surname_birth', ''),
            'gender': gender,
            'deceased': p.get('deceased') == '1',
            'birth_date': birth_display,
            'death_date': death_display,
            'birth_place': p.get('birth_place', ''),
            'profession': p.get('profession', ''),
            'company': p.get('company', ''),
            'email': p.get('email', ''),
            'interests': p.get('interests', ''),
            'activities': p.get('activities', ''),
            'bio_notes': p.get('bio_notes', ''),
            'address': p.get('address', ''),
            'home_tel': p.get('home_tel', ''),
            'mobile': p.get('mobile', ''),
        }
        nodes.append(node)

        # Parent-child edges
        for rel_tag in ['mother', 'father', 'mother2', 'father2', 'mother3', 'father3']:
            parent_id = p.get(rel_tag)
            if parent_id and parent_id in individuals:
                edge_key = (parent_id, pid, 'parent-child')
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append({
                        'source': parent_id,
                        'target': pid,
                        'type': 'parent-child',
                    })

        # Partner edges
        partner_id = p.get('partner')
        if partner_id and partner_id in individuals:
            edge_key = tuple(sorted([pid, partner_id])) + ('partner',)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                edges.append({
                    'source': pid,
                    'target': partner_id,
                    'type': 'partner',
                })

    # Add partnership info from p lines
    for pp in partnerships:
        p1, p2 = pp['person1'], pp['person2']
        edge_key = tuple(sorted([p1, p2])) + ('partner',)
        ptype = PARTNERSHIP_TYPE_MAP.get(pp.get('partnership_type', ''), 'relationship')
        # Update existing edge or create new one
        found = False
        for e in edges:
            sk = tuple(sorted([e['source'], e['target']])) + (e['type'],)
            if sk == edge_key:
                e['partnership_type'] = ptype
                if pp.get('marriage_date'):
                    e['marriage_date'] = parse_date(pp['marriage_date'])
                if pp.get('marriage_location'):
                    e['marriage_location'] = pp['marriage_location']
                found = True
                break
        if not found and p1 in individuals and p2 in individuals:
            seen_edges.add(edge_key)
            edge = {'source': p1, 'target': p2, 'type': 'partner', 'partnership_type': ptype}
            if pp.get('marriage_date'):
                edge['marriage_date'] = parse_date(pp['marriage_date'])
            edges.append(edge)

    # Compute generations via BFS from START
    generations = {}
    if 'START' in individuals:
        generations['START'] = 0
        queue = ['START']
        while queue:
            current = queue.pop(0)
            gen = generations[current]
            p = individuals[current]
            # Parents are gen - 1
            for rel in ['mother', 'father', 'mother2', 'father2']:
                parent_id = p.get(rel)
                if parent_id and parent_id in individuals and parent_id not in generations:
                    generations[parent_id] = gen - 1
                    queue.append(parent_id)
            # Partner is same gen
            partner_id = p.get('partner')
            if partner_id and partner_id in individuals and partner_id not in generations:
                generations[partner_id] = gen
                queue.append(partner_id)
            # Children are gen + 1
            for other_id, other in individuals.items():
                if other_id in generations:
                    continue
                if other.get('mother') == current or other.get('father') == current:
                    generations[other_id] = gen + 1
                    queue.append(other_id)
                elif other.get('mother2') == current or other.get('father2') == current:
                    generations[other_id] = gen + 1
                    queue.append(other_id)

    # Second pass for any disconnected nodes
    for pid in individuals:
        if pid not in generations:
            generations[pid] = 0

    for node in nodes:
        node['generation'] = generations.get(node['id'], 0)

    return {'nodes': nodes, 'edges': edges, 'startPerson': 'START'}


def _is_cjk(s):
    for c in s:
        if '一' <= c <= '鿿' or '㐀' <= c <= '䶿':
            return True
    return False


def main():
    if len(sys.argv) < 2:
        input_file = Path(__file__).parent / '..' / 'Downloads' / 'My-Family-18-Jun-2026-141118359.txt'
    else:
        input_file = Path(sys.argv[1])

    if not input_file.exists():
        print(f"File not found: {input_file}", file=sys.stderr)
        sys.exit(1)

    text = input_file.read_text(encoding='utf-8')
    data = parse_familyscript(text)

    output = Path(__file__).parent / 'data.json'
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Parsed {len(data['nodes'])} individuals, {len(data['edges'])} relationships -> {output}")


if __name__ == '__main__':
    main()
