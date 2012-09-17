var all_posts = {{all_posts}};
var titles = [];
for(var title in all_posts){
    titles.push(title);
}

$(function(){

    var $window = $(window);

    $('.search-query').typeahead({
        source: titles
    });

    $('.navbar-search').submit(function(){
        var title = $(this).find('input').val();
        var permlink = all_posts[title];
        $(this).attr('action', permlink);
    });

    $("a[rel=tooltip]")
        .tooltip();

    $("a[rel=popover]")
        .popover({
            trigger: 'hover'
        });

    $('table')
        .addClass('table table-striped');

    $('pre')
        .addClass('prettyprint pre-scrollable');

    window.prettyPrint && prettyPrint();
});