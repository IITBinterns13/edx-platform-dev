// Generated by CoffeeScript 1.3.3
(function() {

  this.Courseware = (function() {

    Courseware.prefix = '';

    function Courseware() {
      Courseware.prefix = $("meta[name='path_prefix']").attr('content');
      new Navigation;
      new Calculator;
      new FeedbackForm;
      Logger.bind();
      this.bind();
      this.render();
    }

    Courseware.start = function() {
      return new Courseware;
    };

    Courseware.prototype.bind = function() {
      return $('.course-content .sequence, .course-content .tab').bind('contentChanged', this.render);
    };

    Courseware.prototype.render = function() {
      $('.course-content .video').each(function() {
        var id;
        id = $(this).attr('id').replace(/video_/, '');
        return new Video(id, $(this).data('streams'));
      });
      $('.course-content .problems-wrapper').each(function() {
        var id;
        id = $(this).attr('id').replace(/problem_/, '');
        return new Problem(id, $(this).data('url'));
      });
      return $('.course-content .histogram').each(function() {
        var id;
        id = $(this).attr('id').replace(/histogram_/, '');
        return new Histogram(id, $(this).data('histogram'));
      });
    };

    return Courseware;

  })();

}).call(this);