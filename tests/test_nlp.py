"""Step 9 tests: natural language → drawlang."""

import pytest

from editor.app.nlp import translate_command, NLPError


def test_move_absolute():
    assert translate_command("move to 100 200") == ["ma,100,200;"]

def test_move_directional():
    assert translate_command("move right 20") == ["mr,20,0;"]
    assert translate_command("move left 15") == ["mr,-15,0;"]
    assert translate_command("move up 30") == ["mr,0,-30;"]
    assert translate_command("move down 40") == ["mr,0,40;"]

def test_line_directional():
    assert translate_command("line right 100") == ["dl,100,0;"]
    assert translate_command("draw down 50") == ["dl,0,50;"]

def test_rectangle():
    assert translate_command("rect 100 50") == ["rt,100,50;"]
    assert translate_command("rectangle 200 300") == ["rt,200,300;"]

def test_circle():
    assert translate_command("circle 25") == ["ci,25;"]

def test_text_with_angle():
    assert translate_command("text 0 hello") == ["tx,0,hello;"]
    assert translate_command("text 90 BM Global A.S.") == ["tx,90,BM Global A.S.;"]

def test_text_without_angle():
    # Bare "text foo" should default angle to 0
    assert translate_command("write hello world") == ["tx,0,hello world;"]

def test_compound_and():
    result = translate_command("move right 20 and line down 30")
    assert result == ["mr,20,0;", "dl,0,30;"]

def test_compound_semicolon():
    result = translate_command("move right 20; line down 30")
    assert result == ["mr,20,0;", "dl,0,30;"]

def test_czech_directional():
    assert translate_command("posun doprava 10") == ["mr,10,0;"]
    assert translate_command("kresli dolu 15") == ["dl,0,15;"]

def test_raw_passthrough():
    assert translate_command("mr,50,0") == ["mr,50,0;"]

def test_unknown_raises():
    with pytest.raises(NLPError):
        translate_command("do a fancy dance")
