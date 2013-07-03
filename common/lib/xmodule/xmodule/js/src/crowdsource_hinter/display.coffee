class @Hinter
  # The client side code for the crowdsource_hinter.
  # Contains code for capturing problem checks and making ajax calls to
  # the server component.  Also contains styling code to clear default
  # text on a textarea.

  constructor: (element) ->
    @el = $(element).find('.crowdsource-wrapper')
    @url = @el.data('url')
    Logger.listen('problem_graded', @el.data('child-url'), @capture_problem)
    @render()

  capture_problem: (event_type, data, element) =>
    # After a problem gets graded, we get the info here.
    # We want to send this info to the server in another AJAX
    # request.
    answers = data[0]
    response = data[1]
    if response.search(/class="correct/) == -1
      # Incorrect.  Get hints.
      $.postWithPrefix "#{@url}/get_hint", answers, (response) =>
        @render(response.contents)
    else
      # Correct.  Get feedback from students.
      $.postWithPrefix "#{@url}/get_feedback", answers, (response) =>
        @render(response.contents)

  $: (selector) ->
    $(selector, @el)

  bind: =>
    window.update_schematics()
    @$('input.vote').click @vote
    @$('input.submit-hint').click @submit_hint
    @$('.custom-hint').click @clear_default_text
    @$('#answer-tabs').tabs({active: 0})
    @$('.expand-goodhint').click @expand_goodhint

  expand_goodhint: =>
    if @$('.goodhint').css('display') == 'none'
      @$('.goodhint').css('display', 'block')
    else
      @$('.goodhint').css('display', 'none')

  vote: (eventObj) =>
    target = @$(eventObj.currentTarget)
    post_json = {'answer': target.data('answer'), 'hint': target.data('hintno')}
    $.postWithPrefix "#{@url}/vote", post_json, (response) =>
      @render(response.contents)

  submit_hint: (eventObj) =>
    target = @$(eventObj.currentTarget)
    textarea_id = '#custom-hint-' + target.data('answer')
    post_json = {'answer': target.data('answer'), 'hint': @$(textarea_id).val()}
    $.postWithPrefix "#{@url}/submit_hint",post_json, (response) =>
      @render(response.contents)

  clear_default_text: (eventObj) =>
    target = @$(eventObj.currentTarget)
    if target.data('cleared') == undefined
      target.val('')
      target.data('cleared', true)

  render: (content) ->
    if content
      # Trim leading and trailing whitespace
      content = content.replace /^\s+|\s+$/g, ""

    if content
      @el.html(content)
      @el.show()
      JavascriptLoader.executeModuleScripts @el, () =>
        @bind()
      @$('#previous-answer-0').css('display', 'inline')
