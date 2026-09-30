"""Instruction boundaries around Dockerfile escape characters."""

import pytest

from tests.fixtures import dfparser

dfparser = dfparser  # pylint: disable=self-assigning-variable


@pytest.mark.parametrize('escape', ['\\', '`'])
@pytest.mark.parametrize('count', [1, 2, 3])
@pytest.mark.parametrize('suffix', ['', ' \t', '\u00a0'])
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_terminal_escape_instruction_boundaries(dfparser, escape, count, suffix, newline):
    directive = '# escape={}'.format(escape) + newline
    header = 'RUN echo ' + escape * count + suffix + newline
    following = 'FROM next' + newline
    dfparser.content = directive + header + following
    continues = count == 1 and suffix != '\u00a0'
    expected = [
        {'instruction': 'RUN', 'startline': 1, 'endline': 2 if continues else 1,
         'content': header + following if continues else header,
         'value': 'echo FROM next' if continues else 'echo ' + escape * count},
    ]
    if not continues:
        expected.append({'instruction': 'FROM', 'startline': 2, 'endline': 2,
                         'content': following, 'value': 'next'})
    assert dfparser.structure[1:] == expected
    assert dfparser.parent_images == ([] if continues else ['next'])


@pytest.mark.parametrize('escape', ['\\', '`'])
def test_escaped_escape_ends_continued_instruction(dfparser, escape):
    header = 'RUN echo {0}\n    value {0}{0}\n'.format(escape)
    dfparser.content = '# escape={}\n'.format(escape) + header + 'FROM next\n'
    assert dfparser.structure[1:] == [
        {'instruction': 'RUN', 'startline': 1, 'endline': 2,
         'content': header, 'value': 'echo     value ' + escape * 2},
        {'instruction': 'FROM', 'startline': 3, 'endline': 3,
         'content': 'FROM next\n', 'value': 'next'},
    ]


@pytest.mark.parametrize('escape', ['\\', '`'])
def test_heredoc_header_ends_at_escaped_escape(dfparser, escape):
    header = 'RUN cat <<EOF {0}{0}\n'.format(escape)
    body = 'FROM payload\nEOF\n'
    dfparser.content = '# escape={}\n'.format(escape) + header + body + 'FROM next\n'
    assert dfparser.structure[1:] == [
        {'instruction': 'RUN', 'startline': 1, 'endline': 3,
         'content': header + body, 'value': header[4:-1] + '\n' + body.rstrip('\n')},
        {'instruction': 'FROM', 'startline': 4, 'endline': 4,
         'content': 'FROM next\n', 'value': 'next'},
    ]
